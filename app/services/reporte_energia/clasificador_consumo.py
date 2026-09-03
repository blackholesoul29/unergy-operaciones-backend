"""Árbol de decisión para fronteras de Consumo (frt_consumption) -- energía
que el proyecto importa de la red, reportada al ASIC por su propio frt_code
(distinto del de generación del mismo proyecto).

Puerto de process/src/internals/clasificador_consumo.py (repo Reporte-Energia).

No confundir con el "consumo propio" de clasificador.py (autoconsumo del
medidor de GENERACIÓN) -- acá se trata una frontera de Consumo real, con su
propio frt_code, Estado reporte y medidores.

A diferencia de Generación, Consumo no tiene una fuente independiente para
validar cruzado (no existe un "inversores" de consumo) -- el árbol es más
corto, solo dos niveles:

  Caso 'CGM'      -- reporte automático válido y el canal CGM (iae) trae
                     dato real -- se confía en él, cruzándolo contra la
                     mediana histórica si ya existe. Si se sale del rango,
                     una SEGUNDA validación pide los medidores del día y
                     desempata (_veredicto_medidor_vs_cgm): si un medidor
                     completo coincide con el CGM se confía sin revisión (el
                     día de verdad fue distinto), si lo contradice se
                     descarta el CGM y se sigue por 'Medidor', y si ninguno
                     puede opinar queda para revisar.
  Caso 'Medidor'  -- CGM no válido/no disponible. Cada medidor con dato se
                     valida contra la MEDIANA histórica propia
                     (TOLERANCIA_HISTORICO_CONSUMO) en vez de tomar
                     "mayor valor" -- un hueco de telemetría puede acumular
                     horas sin reportar en un pico artificial, y "mayor
                     valor" elegiría sistemáticamente el más inflado.
  Caso 'Histórico' -- ni CGM ni medidor creíble, pero hay historial propio
                     -- mediana × forma horaria. Marca Revisar Manualmente:
                     ningún dato real de ese día respalda la curva
                     completa, es una estimación de punta a punta.
  Caso 'Sin dato' -- nada de lo anterior -- curva vacía, Revisar Manualmente.

Todas las fronteras pasan por el mismo árbol: las listas de excepción por
frontera se eliminaron el 2026-09-02 (ver el bloque de constantes).

Recuperación activa de medidor (ver clasificador.py) aplica igual acá --
se dispara dentro de curvas.curvas_de_frontera() antes de que su resultado
llegue a este árbol.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.services.mgs.gaia_client import GaiaClient
from app.services.reporte_energia import curvas, historial
from app.services.reporte_energia.utils import CURVA_CERO, CURVA_VACIA, HORAS_SOLARES, escalar_curva, curva_a_lista

HORAS = list(range(24))
ESTADOS_AUTOMATICO = {"OK", "WARNING"}

# %: qué tan lejos puede quedar el medidor más cercano de la mediana
# histórica antes de dejar de confiar en él. Bajado de 0.50 a 0.30 (ver MGS
# 0015 El Son Consumo 2026-08-09: un bug de Quoia duplicó el consumo real,
# 38,41 kWh vs mediana 26,795 kWh -- 43,4% de diferencia, pasaba con el 50%
# de antes).
TOLERANCIA_HISTORICO_CONSUMO = 0.30

# Listas de excepción por frontera ELIMINADAS (2026-09-02, decisión de la
# usuaria): todas las fronteras de Consumo pasan por el mismo árbol, sin
# tratos particulares. Lo que había y se quitó, por si alguna vuelve a hacer
# falta:
#   · IGNORAR_CGM {90} -- Chiriguaná Norte 2 Consumo. Su CGM reporta casi
#     siempre el mismo valor que Chiriguaná Norte 4 (confirmado 2026-08-04:
#     configuración de Quoia, frt_codes distintos pero dato compartido), así
#     que se ignoraba el CGM siempre. Sin la lista, esos días se reportan con
#     ese CGM -- riesgo aceptado explícitamente.
#   · VALIDAR_CGM_VS_MEDIDOR {111} + TOLERANCIA_CGM_VS_MEDIDOR (0.50) --
#     Paso Norte Consumo. Bug intermitente de Quoia que reportaba el doble
#     del consumo real (2026-08-03: CGM 69,23 kWh vs medidor 34,615, 2x
#     exacto) con el estado en OK/WARNING. Se cruzaba CGM contra el medidor
#     antes de aceptarlo, y quedaba siempre para revisar.
#     ESTE caso ya NO necesita lista: _veredicto_medidor_vs_cgm cruza CGM
#     contra el medidor para TODAS las fronteras (disparado por el histórico
#     fuera de rango), así que el CGM doblado se descarta solo -- y cuando el
#     día de verdad fue distinto, el mismo cruce lo deja pasar sin revisión,
#     que la lista no sabía hacer.
#   · SIEMPRE_REVISAR {78} -- La Catedral Consumo, patrón atípico donde
#     ninguna validación automática decidía bien sola.
#   · VECINO_HISTORICO_CONSUMO -- permitía que el Caso 'Histórico' usara la
#     mediana y forma horaria de otra frontera del mismo predio (en el
#     pipeline original: Sabana de Torres -> La Reserva) en vez de caer en
#     'Sin dato'. Sin esto, una frontera sin historial propio cae en
#     'Sin dato'.

# %: qué tan lejos puede quedar un medidor del otro (principal vs respaldo)
# antes de dejar de "preferir siempre el principal" cuando no hay mediana
# histórica con qué arbitrar. Diferencias chicas (ej. Sol&Cielo 7 Los Bongos
# 2026-08-03: 22 vs 19,8 kWh, ~10%) no justifican preferir el más alto solo
# por serlo -- pero diferencias grandes (ej. Baraya AUX 2026-08-03: 18,9 vs
# 3,3 kWh, ~83%) ya no son "cuál preferir sin razón", sino que uno de los
# dos medidores probablemente está mal -- ahí se prefiere el de mayor valor
# (una lectura de más se explica más fácil -- medidor caído/mal ubicado --
# que una lectura de menos).
DIFERENCIA_MEDIDORES_ALTA = 0.50

# %: qué tan cerca tiene que estar un medidor COMPLETO del total del CGM para
# que cuente como opinión sobre él (segunda validación, ver
# _veredicto_medidor_vs_cgm). Mucho más estrecho que
# TOLERANCIA_HISTORICO_CONSUMO a propósito: acá no se compara contra una
# estimación (la mediana de otros días) sino contra una lectura del MISMO día
# del mismo medidor físico por otro canal -- si los dos canales miden bien,
# tienen que dar casi lo mismo, y un ±2% no deja pasar ni la mitad ni el doble.
RANGO_CORROBORACION_CONSUMO = 0.02


def _veredicto_medidor_vs_cgm(e_cgm: float, c: dict) -> str:
    """Segunda validación del CGM: qué opina el medidor del día.

    Se llama SOLO cuando el total del CGM ya se salió del rango histórico --
    ahí el histórico dice "este día es raro" pero no sabe si el raro es el
    día (consumo real distinto) o el dato (glitch de Quoia). El medidor sí lo
    sabe: es el mismo medidor físico leído por el canal de monitoreo, un
    camino de telecomunicaciones independiente del canal CGM.

      'corrobora'  -- un medidor completo coincide con el CGM (±2%): el día
                      de verdad fue distinto. Se confía en el CGM y NO se
                      marca revisión (ver Valencia Oriente Consumo).
      'contradice' -- hay medidor completo y ninguno coincide: el dato del
                      CGM está mal. Se descarta y se sigue por el Camino 2
                      (medidor validado contra la mediana), que además SÍ
                      envía matriz de corrección a Quoia -- ver Paso Norte
                      Consumo, cuyo CGM reporta intermitentemente el doble
                      del consumo real con el estado en OK/WARNING (esto
                      reemplaza la lista VALIDAR_CGM_VS_MEDIDOR que había
                      por frontera, ahora vale para todas).
      'sin_dato'   -- ningún medidor completo con dato: nadie puede opinar,
                      queda la revisión manual de siempre.

    Solo un medidor COMPLETO opina: uno con huecos lee de menos por
    definición, así que su diferencia contra el CGM no dice nada.
    """
    hubo_completo = False
    for clave_curva, clave_completo in (
        ("consumo_ppal", "consumo_ppal_completo"),
        ("consumo_resp", "consumo_resp_completo"),
    ):
        curva = c.get(clave_curva)
        if not _tiene_dato(curva) or not c.get(clave_completo):
            continue
        total = float(curva.fillna(0).sum())
        if total <= 0:
            continue
        hubo_completo = True
        if abs(e_cgm - total) / total <= RANGO_CORROBORACION_CONSUMO:
            return "corrobora"
    return "contradice" if hubo_completo else "sin_dato"


def _curvas_medidor(
    gaia: GaiaClient, border_meta: dict | None, mapa_medidor_nodo: dict[int, int],
    fecha_str: str, frt_code: str, mediana: float | None = None,
) -> dict:
    """Lecturas del medidor por el canal de monitoreo. `mediana` (cuando se
    tiene) habilita la recuperación activa por valor sospechoso -- si el
    medidor mismo viene con un glitch, se re-interroga ANTES de usarlo para
    juzgar al CGM."""
    return curvas.curvas_de_frontera(
        gaia, mapa_medidor_nodo,
        border_meta.get("main_meter") if border_meta else None,
        border_meta.get("backup_meter") if border_meta else None,
        fecha_str, frt_code, mediana_referencia=mediana,
    )


def _tiene_dato(curva: pd.Series | None) -> bool:
    return isinstance(curva, pd.Series) and curva.notna().any()


def _en_rango_historico(curva: pd.Series, mediana: float) -> bool:
    total = curva.fillna(0).sum()
    return mediana > 0 and abs(total - mediana) / mediana <= TOLERANCIA_HISTORICO_CONSUMO


def _medidor_mas_cercano(curva_a: pd.Series, curva_b: pd.Series, mediana: float) -> tuple[pd.Series, str, bool]:
    """Entre dos medidores con dato real, (curva, 'principal'/'respaldo', en_rango)
    -- el más CERCANO a la mediana histórica, no el de mayor valor."""
    total_a = curva_a.fillna(0).sum()
    total_b = curva_b.fillna(0).sum()
    if abs(total_a - mediana) <= abs(total_b - mediana):
        return curva_a, "principal", _en_rango_historico(curva_a, mediana)
    return curva_b, "respaldo", _en_rango_historico(curva_b, mediana)


def rellenar_horas_faltantes_consumo(
    db: Session, curva: pd.Series, frontera_id: int, fecha: date,
) -> tuple[pd.Series, set[int]]:
    """Rellena las horas en NaN de un Caso 'Medidor' con el histórico
    horario propio -- último recurso de la acción manual 'Rellenar horas'
    (POST /fronteras/{id}/rellenar-horario en reporte_energia.py), después
    de intentar medidor cruzado. No existe reconectador/Solenium para
    Consumo, así que histórico es la única fuente además del otro medidor."""
    if not curva.isna().any():
        return curva, set()

    mediana, _ = historial.get_mediana_consumo(db, frontera_id, fecha)
    if mediana is None:
        return curva, set()
    forma, _ = historial.get_forma_consumo(db, frontera_id, fecha)
    if forma is None:
        return curva, set()

    curva_historica = escalar_curva(forma, mediana)
    curva = curva.copy()
    horas_faltantes = set(curva[curva.isna()].index)
    for h in horas_faltantes:
        curva[h] = curva_historica[h]
    return curva, horas_faltantes


def clasificar_consumo(
    db: Session,
    gaia: GaiaClient,
    frontera_id: int,
    frt_code: str,
    border_meta: dict | None,
    mapa_medidor_nodo: dict[int, int],
    fecha: date,
) -> dict:
    """Clasifica una frontera de Consumo para un día. Retorna un dict listo
    para volcar en ReporteEnergiaConsumo."""
    fecha_str = str(fecha)

    border_id = border_meta.get("border_id") if border_meta else None
    reporte = gaia.get_border_report_status(int(border_id), fecha_str) if border_id else None
    reporte_valido = bool(reporte) and str(reporte.get("status", "")).upper() in ESTADOS_AUTOMATICO
    estado_reporte = str(reporte.get("status")).upper() if reporte else None
    curva_cgm = (
        pd.Series(reporte["reported_data_main"][:24], index=HORAS, dtype=float)
        if reporte and reporte.get("reported_data_main") else CURVA_CERO.copy()
    )
    e_cgm = float(curva_cgm.fillna(0).sum())

    cgm_ok = reporte_valido and e_cgm > 0
    # Se llenan una sola vez: si la segunda validación las pidió para juzgar
    # al CGM, el Camino 2 las reusa en vez de volver a pedirlas.
    curvas_medidor: dict | None = None

    if cgm_ok:
        resultado_cgm = {
            "caso": "CGM", "energia_final_kwh": e_cgm, "curva_final": curva_cgm,
            "medidor_usado": "cgm", "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
            "horas_rellenadas_historico": None, "recuperacion_datos": None,
        }
        # Blindaje contra outliers: 'reporte automático válido' por sí solo no
        # protege de un CGM que ese día reportó algo raro. En cuanto hay
        # mediana histórica (aunque se haya construido con días de CGM, ver
        # CASOS_CONFIABLES_CONSUMO), se cruza igual que ya se hace para
        # 'Medidor' -- mientras no haya mediana (arranque desde cero), se
        # confía solo en el status de Quoia.
        mediana, _ = historial.get_mediana_consumo(db, frontera_id, fecha)
        if mediana is not None and not _en_rango_historico(curva_cgm, mediana):
            # Segunda validación: el histórico solo detecta que el día se
            # salió de lo normal, no si la culpa es del día o del dato. Acá
            # -- y solo acá, en el día desviado -- se piden los medidores
            # para que desempaten (ver _veredicto_medidor_vs_cgm). Las
            # fronteras cuyo CGM cae dentro del rango nunca llegan a este
            # fetch, así que no agrega llamadas a Quoia en el día normal.
            curvas_medidor = _curvas_medidor(gaia, border_meta, mapa_medidor_nodo, fecha_str, frt_code, mediana)
            veredicto = _veredicto_medidor_vs_cgm(e_cgm, curvas_medidor)
            if veredicto == "contradice":
                cgm_ok = False  # se descarta el CGM -- sigue por el Camino 2
            elif veredicto == "sin_dato":
                resultado_cgm["revisar_manualmente"] = True
        if cgm_ok:
            return resultado_cgm

    resultado = _clasificar_por_medidor_o_historico(
        db, gaia, frontera_id, frt_code, border_meta, mapa_medidor_nodo, fecha, fecha_str, e_cgm, estado_reporte,
        c=curvas_medidor,
    )

    # Relleno horario (2026-08-12): solo el cero directo se aplica
    # automático acá. Medidor cruzado/histórico dejaron de rellenar solos
    # (mismo cambio que Generación) -- quedan disponibles como acción
    # manual desde el front (POST /fronteras/{id}/rellenar-horario en
    # reporte_energia.py), que decide la persona explícitamente.
    curva_actual = resultado.get("curva_final")
    horas_ventana_solar_directo: set[int] = set()
    if resultado.get("caso") == "Medidor" and isinstance(curva_actual, pd.Series) and curva_actual.isna().any():
        # Huecos DENTRO de la ventana solar se llenan en 0.0 directo -- esta
        # frontera es el consumo de red del MISMO proyecto de generación
        # solar, así que durante horas de sol alto el consumo de red ya se
        # espera en ~0 (los propios paneles cubren la carga del sitio) --
        # mismo principio que Generación para las horas FUERA de la
        # ventana solar. No es una estimación, es una certeza física, así
        # que NO marca Revisar Manualmente.
        huecos_iniciales = curva_actual[curva_actual.isna()].index
        horas_ventana_solar_directo = {h for h in huecos_iniciales if h in HORAS_SOLARES}
        if horas_ventana_solar_directo:
            curva_actual = curva_actual.copy()
            curva_actual[sorted(horas_ventana_solar_directo)] = 0.0
            resultado["curva_final"] = curva_actual
            resultado["energia_final_kwh"] = float(curva_actual.fillna(0).sum())

        # Un hueco fuera de la ventana solar (madrugada/noche) sin dato real
        # sí preocupa -- ahí es consumo real de red, no hay certeza física
        # que ayude, y sin el relleno automático de medidor cruzado/
        # histórico no queda nada más con qué completarlo desde acá.
        if curva_actual.isna().any():
            resultado["revisar_manualmente"] = True

    resultado.setdefault("revisar_manualmente", False)
    resultado["horas_rellenadas_historico"] = None
    resultado["horas_rellenadas_medidor_cruzado"] = None
    return resultado


def _clasificar_por_medidor_o_historico(
    db: Session, gaia: GaiaClient, frontera_id: int, frt_code: str, border_meta: dict | None,
    mapa_medidor_nodo: dict[int, int], fecha: date, fecha_str: str, e_cgm: float, estado_reporte: str | None,
    c: dict | None = None,
) -> dict:
    if c is None:
        c = _curvas_medidor(gaia, border_meta, mapa_medidor_nodo, fecha_str, frt_code)
    resultado = _decidir_medidor_o_historico(db, frontera_id, fecha, e_cgm, estado_reporte, c)
    # Curvas de referencia tal como estaban al momento de clasificar -- ya se
    # tenían que pedir de todas formas para esta rama, así que persistirlas
    # no agrega ninguna llamada nueva a Quoia (ver mismo fix en
    # clasificador.py -- MGS 0032 El Paso Norte 2026-08-05).
    resultado["curva_medidor_principal"] = curva_a_lista(c["consumo_ppal"])
    resultado["curva_medidor_respaldo"] = curva_a_lista(c["consumo_resp"])
    return resultado


def _decidir_medidor_o_historico(
    db: Session, frontera_id: int, fecha: date, e_cgm: float, estado_reporte: str | None, c: dict,
) -> dict:
    # Para una frontera de Consumo, "generación" (eae) y "consumo" (iae) del
    # mismo medidor son ambos relevantes en teoría, pero lo que interesa acá
    # es la variable iae de ESTE medidor -- ya viene calculada en
    # 'consumo_ppal'/'consumo_resp' (mismo helper que usa clasificador.py
    # para el autoconsumo del medidor de generación, reusado acá porque es
    # exactamente la misma cuenta: eae/iae del nodo resuelto por frt_code).
    curva_ppal, curva_resp = c["consumo_ppal"], c["consumo_resp"]
    recuperacion_datos = c.get("recuperacion_datos")

    tiene_ppal = _tiene_dato(curva_ppal)
    tiene_resp = _tiene_dato(curva_resp)

    mediana = None
    if tiene_ppal or tiene_resp:
        mediana, _ = historial.get_mediana_consumo(db, frontera_id, fecha)

    if tiene_ppal and tiene_resp:
        if mediana is not None:
            curva, medidor_usado, en_rango = _medidor_mas_cercano(curva_ppal, curva_resp, mediana)
            if en_rango:
                return {
                    "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()),
                    "curva_final": curva, "medidor_usado": medidor_usado,
                    "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                    "recuperacion_datos": recuperacion_datos,
                }
        else:
            # Sin mediana historica para comparar -- no se descarta el dato
            # real solo porque no hay con que cruzarlo, esté completo o no
            # (ver GD Polaris 2 Consumo 2026-08-03: 19 de 24 horas reales,
            # faltaban las últimas 5-6 -- antes se vaciaba la curva entera
            # por ese hueco parcial).
            total_ppal = float(curva_ppal.fillna(0).sum())
            total_resp = float(curva_resp.fillna(0).sum())
            mayor = max(total_ppal, total_resp)
            diferencia = abs(total_ppal - total_resp) / mayor if mayor > 0 else 0.0

            if diferencia > DIFERENCIA_MEDIDORES_ALTA:
                # Diferencia demasiado grande para ser solo ruido -- uno de
                # los dos medidores probablemente está mal (ver Baraya AUX
                # 2026-08-03). Sin mediana con qué arbitrar, se prefiere el
                # de mayor valor.
                curva = curva_ppal if total_ppal >= total_resp else curva_resp
                return {
                    "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                    "medidor_usado": "principal_sin_historico" if curva is curva_ppal else "respaldo_sin_historico",
                    "revisar_manualmente": True,
                    "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                    "recuperacion_datos": recuperacion_datos,
                }

            # Diferencia chica -- se prefiere SIEMPRE el principal (ya
            # sabemos que tiene dato, por estar en este 'if') -- no el de
            # mayor valor: decisión explícita del usuario tras ver Sol&Cielo
            # 7 Los Bongos Consumo 2026-08-03, donde el respaldo (22 kWh)
            # superaba al principal (19,8 kWh) sin ninguna razón para
            # preferirlo solo por ser más alto. Marcado para revisar a mano
            # porque nadie confirmó que el nivel sea el correcto.
            return {
                "caso": "Medidor", "energia_final_kwh": total_ppal, "curva_final": curva_ppal,
                "medidor_usado": "principal_sin_historico", "revisar_manualmente": True,
                "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                "recuperacion_datos": recuperacion_datos,
            }
    elif tiene_ppal or tiene_resp:
        curva = curva_ppal if tiene_ppal else curva_resp
        if mediana is None:
            # Mismo criterio que arriba -- se usa el dato disponible aunque
            # no esté completo, no hay con qué cruzarlo de todas formas.
            return {
                "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                "medidor_usado": "principal_sin_historico" if tiene_ppal else "respaldo_sin_historico",
                "revisar_manualmente": True,
                "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                "recuperacion_datos": recuperacion_datos,
            }
        if _en_rango_historico(curva, mediana):
            return {
                "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                "medidor_usado": "principal" if tiene_ppal else "respaldo",
                "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                "recuperacion_datos": recuperacion_datos,
            }

    if mediana is None:
        mediana, _ = historial.get_mediana_consumo(db, frontera_id, fecha)

    # Bug real (La Catedral Consumo, MINIGRANJA SOLAR CAÑAHUATE SER AUX --
    # 13/96 filas 'Histórico' en producción, confirmado 2026-08-27): antes,
    # con mediana pero SIN forma horaria (get_mediana_consumo y
    # get_forma_consumo exigen ventanas distintas -- mediana solo pide un
    # total válido por día, forma exige además la curva COMPLETA y con
    # total > 0), se reportaba igual "caso: Histórico" con
    # energia_final_kwh = mediana (ej. 6.9 kWh) pero curva_final en
    # CURVA_CERO -- el total y la curva quedaban contradictorios, y la
    # tabla de corrección manual del frontend mostraba 24 ceros aunque el
    # resumen dijera otro número. Mismo criterio que ya usa
    # reconectador.rellenar_horas_faltantes: la mediana sola nunca alcanza,
    # hace falta la forma también antes de reportar nada como Histórico.
    if mediana is not None:
        forma, _ = historial.get_forma_consumo(db, frontera_id, fecha)
        if forma is not None:
            curva_historico = escalar_curva(forma, mediana)
            return {
                "caso": "Histórico", "energia_final_kwh": mediana, "curva_final": curva_historico,
                "medidor_usado": "historico", "revisar_manualmente": True,
                "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                "recuperacion_datos": recuperacion_datos,
            }

    return {
        "caso": "Sin dato", "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
        "medidor_usado": "ninguno", "revisar_manualmente": True,
        "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
        "recuperacion_datos": recuperacion_datos,
    }
