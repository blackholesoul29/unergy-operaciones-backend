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
                     dato real -- se confía en él a ciegas, salvo las
                     fronteras en FRONTERAS_VALIDAR_CGM_VS_MEDIDOR (bug
                     puntual de Quoia, se descarta solo si no cuadra) y
                     FRONTERAS_CONSUMO_IGNORAR_CGM (medidor compartido con
                     otra frontera, se ignora siempre).
  Caso 'Medidor'  -- CGM no válido/no disponible. Cada medidor con dato se
                     valida contra la MEDIANA histórica propia
                     (TOLERANCIA_HISTORICO_CONSUMO = ±50%) en vez de tomar
                     "mayor valor" -- un hueco de telemetría puede acumular
                     horas sin reportar en un pico artificial, y "mayor
                     valor" elegiría sistemáticamente el más inflado.
  Caso 'Histórico' -- ni CGM ni medidor creíble, pero hay historial propio
                     (o del vecino de predio, ver VECINO_HISTORICO_CONSUMO)
                     -- mediana × forma horaria. NO marca Revisar
                     Manualmente: sí hay con qué comparar y la curva no
                     queda vacía.
  Caso 'Sin dato' -- nada de lo anterior -- curva vacía, Revisar Manualmente.

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
from app.services.reporte_energia.utils import CURVA_CERO, CURVA_VACIA, escalar_curva

HORAS = list(range(24))
ESTADOS_AUTOMATICO = {"OK", "WARNING"}

# %: qué tan lejos puede quedar el medidor más cercano de la mediana
# histórica antes de dejar de confiar en él.
TOLERANCIA_HISTORICO_CONSUMO = 0.50

# frontera_id (Consumo) -> frontera_id (Consumo del vecino de predio) --
# para el Caso 'Histórico' cuando la frontera nunca ha tenido un día de
# Caso 'Medidor' real. Confirmar ids reales contra la BD ("MGS 0033 - Sabana
# de Torres" -> "MGS 0012 - La Reserva" en el pipeline original).
VECINO_HISTORICO_CONSUMO: dict[int, int] = {}

# frontera_id (Consumo) donde Quoia tiene un bug intermitente confirmado:
# reporta el doble de la energía real de Consumo aunque el estado del
# reporte diga OK/WARNING (Paso Norte, 2026-08-03: CGM=69,23 kWh vs
# medidor=34,615 kWh, exactamente 2x -- el día anterior CGM y medidor
# coincidían exacto, confirma que es intermitente, no un offset fijo).
# Mientras Quoia lo soluciona de su lado, para estas fronteras puntuales SÍ
# se consulta el medidor aunque CGM parezca válido, para descartar el
# reporte si no cuadra. No se aplica a todas las fronteras de Consumo para
# no sumarle una llamada extra a Quoia, todos los días, a las ~40+ que hoy
# resuelven solo con CGM sin tocar el medidor.
FRONTERAS_VALIDAR_CGM_VS_MEDIDOR: set[int] = {111}  # Paso Norte Consumo

# %: qué tan lejos puede quedar CGM del medidor antes de dejar de confiar
# en el reporte automático, para las fronteras de FRONTERAS_VALIDAR_CGM_VS_MEDIDOR.
# Mismo valor que TOLERANCIA_HISTORICO_CONSUMO (±50%) -- generoso a propósito,
# CGM y medidor son dos canales físicos distintos y pueden divergir algo por
# su cuenta; lo que se busca descartar es un error tipo "el doble" (100%),
# no una diferencia normal entre ambos.
TOLERANCIA_CGM_VS_MEDIDOR = 0.50

# frontera_id (Consumo) donde Quoia comparte el mismo medidor físico entre
# dos fronteras -- confirmado 2026-08-04: MGS 0075 Chiriguaná Norte 2
# (frontera_id=90) reporta casi siempre el mismo valor de CGM que MGS 0077
# Chiriguaná Norte 4 (frt_codes distintos, cada uno registrado aparte en
# Quoia), configuración de Quoia, no un bug del lado de acá (mismo tipo de
# hallazgo que el medidor compartido entre estas mismas dos fronteras, ya
# aceptado 2026-07-25). A diferencia de FRONTERAS_VALIDAR_CGM_VS_MEDIDOR
# (que solo descarta CGM si no cuadra contra el medidor), acá se ignora CGM
# siempre -- el problema no es que a veces se equivoque mucho, es que el
# dato en sí no es confiablemente el de esta frontera.
FRONTERAS_CONSUMO_IGNORAR_CGM: set[int] = {90}  # Chiriguaná Norte 2 Consumo

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


def _tiene_dato(curva: pd.Series | None) -> bool:
    return isinstance(curva, pd.Series) and curva.notna().any()


def _cgm_confiable(e_cgm: float, curva_ppal: pd.Series, curva_resp: pd.Series) -> bool:
    """True si no hay medidor con qué cruzar (se confía en CGM como
    siempre) o si al menos uno de los dos medidores coincide con CGM
    dentro de tolerancia. False si ambos medidores tienen dato y ninguno
    se acerca -- ahí no se confía en CGM."""
    totales = [c.fillna(0).sum() for c in (curva_ppal, curva_resp) if _tiene_dato(c)]
    if not totales:
        return True
    return any(t > 0 and abs(e_cgm - t) / t <= TOLERANCIA_CGM_VS_MEDIDOR for t in totales)


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


def _rellenar_horas_faltantes_consumo(
    db: Session, curva: pd.Series, frontera_id: int, fecha: date,
) -> tuple[pd.Series, set[int]]:
    """Rellena las horas en NaN de un Caso 'Medidor' ya aceptado con el
    histórico horario propio -- no existe reconectador para Consumo, así
    que este es el único recurso de relleno horario disponible."""
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

    cgm_ok = reporte_valido and e_cgm > 0 and frontera_id not in FRONTERAS_CONSUMO_IGNORAR_CGM
    if cgm_ok and frontera_id in FRONTERAS_VALIDAR_CGM_VS_MEDIDOR:
        main_meter = border_meta.get("main_meter") if border_meta else None
        backup_meter = border_meta.get("backup_meter") if border_meta else None
        c = curvas.curvas_de_frontera(gaia, mapa_medidor_nodo, main_meter, backup_meter, fecha_str, frt_code)
        if not _cgm_confiable(e_cgm, c["consumo_ppal"], c["consumo_resp"]):
            cgm_ok = False

    if cgm_ok:
        return {
            "caso": "CGM", "energia_final_kwh": e_cgm, "curva_final": curva_cgm,
            "medidor_usado": "cgm", "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
            "horas_rellenadas_historico": None, "recuperacion_datos": None,
        }

    resultado = _clasificar_por_medidor_o_historico(
        db, gaia, frontera_id, frt_code, border_meta, mapa_medidor_nodo, fecha, fecha_str, e_cgm, estado_reporte,
    )

    # Relleno de horas puntuales (2026-07-25): un Caso 'Medidor' ya aceptado
    # puede traer huecos puntuales (el medidor dejó de reportar a media
    # tarde, por ejemplo) -- se rellenan con el histórico horario propio
    # (no hay reconectador para Consumo). El total se recalcula sobre la
    # curva ya rellenada; si aun así quedan horas sin cubrir, se marca
    # Revisar Manualmente.
    curva_actual = resultado.get("curva_final")
    horas_historico: set[int] = set()
    if resultado.get("caso") == "Medidor" and isinstance(curva_actual, pd.Series) and curva_actual.isna().any():
        curva_rellenada, horas_historico = _rellenar_horas_faltantes_consumo(db, curva_actual, frontera_id, fecha)
        if horas_historico:
            resultado["curva_final"] = curva_rellenada
            resultado["energia_final_kwh"] = float(curva_rellenada.fillna(0).sum())
        if curva_rellenada.isna().any():
            resultado["revisar_manualmente"] = True

    resultado.setdefault("revisar_manualmente", False)
    resultado["horas_rellenadas_historico"] = sorted(horas_historico) or None
    return resultado


def _clasificar_por_medidor_o_historico(
    db: Session, gaia: GaiaClient, frontera_id: int, frt_code: str, border_meta: dict | None,
    mapa_medidor_nodo: dict[int, int], fecha: date, fecha_str: str, e_cgm: float, estado_reporte: str | None,
) -> dict:
    main_meter = border_meta.get("main_meter") if border_meta else None
    backup_meter = border_meta.get("backup_meter") if border_meta else None
    c = curvas.curvas_de_frontera(gaia, mapa_medidor_nodo, main_meter, backup_meter, fecha_str, frt_code)
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

    fuente_id = frontera_id
    if mediana is None and frontera_id in VECINO_HISTORICO_CONSUMO:
        fuente_id = VECINO_HISTORICO_CONSUMO[frontera_id]
        mediana, _ = historial.get_mediana_consumo(db, fuente_id, fecha)

    if mediana is not None:
        forma, _ = historial.get_forma_consumo(db, fuente_id, fecha)
        curva_historico = escalar_curva(forma, mediana) if forma is not None else CURVA_CERO.copy()
        medidor_usado = "historico" if fuente_id == frontera_id else "historico_vecino"
        return {
            "caso": "Histórico", "energia_final_kwh": mediana, "curva_final": curva_historico,
            "medidor_usado": medidor_usado, "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
            "recuperacion_datos": recuperacion_datos,
        }

    return {
        "caso": "Sin dato", "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
        "medidor_usado": "ninguno", "revisar_manualmente": True,
        "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
        "recuperacion_datos": recuperacion_datos,
    }
