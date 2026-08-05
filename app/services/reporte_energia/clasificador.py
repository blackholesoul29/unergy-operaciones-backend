"""Árbol de decisión: asigna Caso 0-8 a cada frontera de Generación para un día.

Puerto de process/src/internals/clasificador.py (repo Reporte-Energia).

Diferencias con el pipeline original:
  - El CGM se lee con GaiaClient.get_border_report_status(border_id, fecha),
    que ya filtra por la fecha exacta -- así que 'reporte_valido' se
    simplifica a "hubo respuesta para esa fecha Y su status es OK/WARNING",
    sin necesitar comparar contra un 'last_report_date' aparte.
  - Recuperación activa de medidor (interrogación WebSocket a Quoia, ver
    app/services/reporte_energia/recuperacion.py) ya está portada -- vive
    dentro de curvas.curvas_de_frontera(), que la dispara automáticamente
    cuando la lectura pasiva de un medidor sale incompleta, antes de que su
    resultado llegue a este árbol de decisión.

Nota sobre nombres: 'e_cgm' (reporte oficial de Quoia/ASIC) y 'e_nodo' (curva
del nodo de monitoreo en tiempo real) son dos fuentes físicas distintas que
pueden no coincidir en el tiempo. Si el reporte automático de Quoia es
válido para ese día ('reporte_valido'), se valida/reporta con e_cgm (Casos 1,
5). Si no, e_cgm deja de ser la referencia -- se valida con e_nodo vs
inversores (Casos 2/3/4, 5).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient
from app.services.reporte_energia import curvas, datos_crudos, solenium as solenium_svc, reconectador, historial
from app.services.reporte_energia.utils import CURVA_CERO, CURVA_VACIA, escalar_curva, escalar_curva_con_huecos

HORAS = list(range(24))

CASOS_CON_RELLENO_HORARIO = {2, 3, 4, 5, 7, 8}
RANGO_ERROR         = 6.0               # %: error aceptable [-6%, +6%]
ESTADOS_AUTOMATICO  = {"OK", "WARNING"}  # estados en que el reporte ASIC de hoy es válido

# frontera_id de proyectos sin inversores (nunca registrados en Solenium)
# cuyo medidor de nodo se sabe que sub-reporta crónicamente frente a la
# energía real, sin forma de calcular un factor de corrección. Confirmar
# los ids reales contra la BD ("GD Agustín 2" en el pipeline original).
MEDIDORES_SIN_INVERSOR_SOSPECHOSOS: set[int] = set()

# frontera_id de proyectos cuyo CGM lo hace al ASIC otra empresa distinta a
# Unergy -- no aplica este árbol de Casos. El medidor de nodo de Quoia no
# tiene telemetría (confirmado en vivo: energia_medidor_principal/respaldo_kwh
# siempre 0), así que mientras no se suba el Excel del tercero para el día
# (POST /fronteras/{id}/cargar-excel-terceros) queda en caso=0/"externo" con
# revisar_manualmente=True -- ver clasificar_generacion() más abajo.
# 79 = Complejo Industrial Cedillanos (Frt88292).
FRONTERAS_TERCEROS: set[int] = {79}


def _en_rango(error: float | None) -> bool:
    return error is not None and abs(error) <= RANGO_ERROR


def _error_con_curva(e_inv: float, curva: pd.Series) -> float | None:
    if e_inv == 0:
        return None
    e_nodo = curva.fillna(0).sum()
    return (e_inv - e_nodo) / e_inv * 100


def _tiene_dato(curva: pd.Series | None) -> bool:
    return isinstance(curva, pd.Series) and curva.notna().any()


def _mejor_medidor(curva_a: pd.Series, curva_b: pd.Series) -> pd.Series:
    """Entre dos curvas de medidor, la de mayor energía total -- cubre a la
    vez "solo una tiene dato" y "ambas reportan, hay que elegir" (convención:
    se prefiere el de mayor valor cuando no hay CGM ni inversores contra qué
    validar). Usada SOLO como referencia para calcular el error vs inversores
    (Casos 2/3/4) -- ahí sí importa la magnitud, porque decide si el día es
    Caso 3 o Caso 4. NO usar para decidir qué medidor reportar directamente
    (ver _principal_o_respaldo)."""
    return curva_a if curva_a.fillna(0).sum() >= curva_b.fillna(0).sum() else curva_b


def _principal_o_respaldo(curva_ppal: pd.Series, curva_resp: pd.Series) -> pd.Series:
    """Para reportar un medidor directo sin nada contra qué validar --
    prefiere SIEMPRE el principal si tiene dato; el respaldo solo si el
    principal no tiene nada. No el de mayor valor (decisión del usuario tras
    ver Sol&Cielo 7 Los Bongos Consumo 2026-08-03, mismo criterio aplicado
    ahí en clasificador_consumo.py)."""
    return curva_ppal if _tiene_dato(curva_ppal) else curva_resp


def _decidir_caso(
    db: Session,
    frontera_id: int,
    fecha: date,
    fecha_str: str,
    e_cgm: float,
    curva_cgm: pd.Series,
    reporte_valido: bool,
    curva_ppal: pd.Series,
    curva_resp: pd.Series,
    completo_ppal: bool,
    completo_resp: bool,
    e_inv: float,
    e_inv_incompleto: float | None,
    curva_solenium: pd.Series,
    id_solenium: int | None,
    node_ppal: int | None,
    gaia: GaiaClient,
    sol: SoleniumClient,
) -> dict:
    """Puerto de _clasificar_fila(). Devuelve {'caso', 'energia_final_kwh',
    'curva_final', 'medidor_usado', ...}."""

    # --- Caso 1: reporte ASIC válido hoy y error en rango ---
    if reporte_valido and e_inv > 0 and e_cgm > 0 and _en_rango(_error_con_curva(e_inv, curva_cgm)):
        return {"caso": 1, "energia_final_kwh": e_cgm, "curva_final": curva_cgm, "medidor_usado": "cgm"}

    # --- Casos 2/3/4: reporte no válido, o CGM no valida contra inversores ---
    if e_inv > 0:
        error_ppal = _error_con_curva(e_inv, curva_ppal) if _tiene_dato(curva_ppal) else None
        error_resp = _error_con_curva(e_inv, curva_resp) if _tiene_dato(curva_resp) else None

        if _en_rango(error_ppal) and completo_ppal:
            return {"caso": 2, "energia_final_kwh": float(curva_ppal.fillna(0).sum()), "curva_final": curva_ppal, "medidor_usado": "principal"}
        if _en_rango(error_resp) and completo_resp:
            return {"caso": 2, "energia_final_kwh": float(curva_resp.fillna(0).sum()), "curva_final": curva_resp, "medidor_usado": "respaldo"}

        # Ningún medidor corrige -- distinguir Caso 3 (error positivo) de Caso 4 (negativo)
        curva_ref = _mejor_medidor(curva_ppal, curva_resp)
        error_ref = _error_con_curva(e_inv, curva_ref) if _tiene_dato(curva_ref) else None

        if error_ref is None or error_ref > 0:
            # Caso 3: medidores subreportan -> inversores × factor de pérdida
            fp_val, fp_calc = historial.get_factor_perdida_detalle(db, frontera_id, fecha)
            if fp_val is None:
                return {
                    "caso": 3, "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
                    "fp": None, "fp_calculada": None, "revisar_manualmente": True,
                    "medidor_usado": "revisar", "error_final_pct": error_ref,
                }
            e_fp = e_inv * fp_val
            curva_inv = escalar_curva(curva_solenium, e_fp) if isinstance(curva_solenium, pd.Series) else CURVA_CERO.copy()
            return {
                "caso": 3, "energia_final_kwh": e_fp, "curva_final": curva_inv,
                "fp": fp_val, "fp_calculada": fp_calc, "medidor_usado": "inversores",
                "error_final_pct": error_ref,
            }
        else:
            # Caso 4: medidores sobrereportan -> medidor de mayor valor
            return {
                "caso": 4, "energia_final_kwh": float(curva_ref.fillna(0).sum()), "curva_final": curva_ref,
                "medidor_usado": "principal" if curva_ref is curva_ppal else "respaldo",
            }

    # --- Caso 5: tengo medidores pero no inversores ---
    if e_inv == 0 and e_cgm > 0:
        if reporte_valido:
            return {"caso": 5, "energia_final_kwh": e_cgm, "curva_final": curva_cgm, "medidor_usado": "cgm"}

        curva = _principal_o_respaldo(curva_ppal, curva_resp)
        if not _tiene_dato(curva):
            # Medidor totalmente caído -- volver a confiar en CGM sería
            # recaer en la misma fuente que esta rama ya decidió no usar. Si
            # hay inversores (aunque el total del día haya quedado parcial),
            # se prefieren (mismo mecanismo de FP que Caso 3). El
            # reconectador es el segundo intento. CGM queda como último
            # recurso si ninguno de los dos tiene nada.
            if e_inv_incompleto:
                fp_val, fp_calc = historial.get_factor_perdida_detalle(db, frontera_id, fecha)
                if fp_val is not None and isinstance(curva_solenium, pd.Series):
                    e_fp = e_inv_incompleto * fp_val
                    return {
                        "caso": 5, "energia_final_kwh": e_fp,
                        "curva_final": escalar_curva_con_huecos(curva_solenium, e_fp),
                        "fp": fp_val, "fp_calculada": fp_calc,
                        "medidor_usado": "inversores", "revisar_manualmente": True,
                    }
            if id_solenium is not None:
                curva_reconectador = reconectador.get_curva_reconectador(sol, int(id_solenium), fecha_str)
                if curva_reconectador is not None and curva_reconectador.fillna(0).sum() > 0:
                    return {
                        "caso": 5, "energia_final_kwh": float(curva_reconectador.fillna(0).sum()),
                        "curva_final": curva_reconectador, "medidor_usado": "reconectador",
                        "revisar_manualmente": True,
                    }
            return {"caso": 5, "energia_final_kwh": e_cgm, "curva_final": curva_cgm, "medidor_usado": "cgm"}

        sospechoso = frontera_id in MEDIDORES_SIN_INVERSOR_SOSPECHOSOS
        resultado = {
            "caso": 5, "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
            "medidor_usado": "principal" if curva is curva_ppal else "respaldo",
        }
        if sospechoso:
            resultado["revisar_manualmente"] = True
        return resultado

    # --- Caso 5 (sin CGM): sin inversores Y sin reporte CGM ese día, pero el
    # medidor sí tiene dato real -- usarlo directo es más preciso que
    # reconstruir de datos crudos (que dependen de la frecuencia de muestreo
    # de la API, ver San Pelayo 2026-08-03: crudos a media resolución dio
    # ~14% menos que el medidor). Solo entra si e_cgm<=0 -- el caso e_cgm>0
    # ya lo maneja el bloque de arriba. Si el medidor TAMBIÉN está caído, no
    # se hace nada acá y sigue cayendo a la cadena de crudos de siempre.
    if e_cgm <= 0:
        curva = _principal_o_respaldo(curva_ppal, curva_resp)
        if _tiene_dato(curva):
            return {
                "caso": 5, "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                "medidor_usado": "principal_sin_cgm" if curva is curva_ppal else "respaldo_sin_cgm",
                "revisar_manualmente": True,
            }

    # --- Casos 6/7/8: ni CGM ni medidor ni inversores tienen nada ---
    if e_inv_incompleto:
        return {
            "caso": 3, "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
            "fp": None, "fp_calculada": None, "medidor_usado": "revisar", "revisar_manualmente": True,
        }

    # El reconectador se intenta ANTES que datos crudos (no solo como
    # rescate de un aparente apagado) -- validado dos veces contra un valor
    # real (Sabana de Torres 2026-07-25: 25 de 27 días entre 1-3% de CGM
    # real; La Mesa 2026-08-03: 5.431,85 kWh vs medidor 5.434,21 kWh, ~0,04%
    # de diferencia) mientras que crudos puede tener problemas de
    # resolución de muestreo (San Pelayo, ~14% por debajo del medidor) o
    # hasta de escala de unidades (Polaris 1/2, ~1.150x por un nodo que
    # reporta en W en vez de kW). Se marca 'Revisar Manualmente' siempre
    # que se use: un proyecto que llega hasta acá no tiene ninguna otra
    # fuente para confirmar el signo/magnitud del reconectador.
    if id_solenium is not None:
        curva_reconectador = reconectador.get_curva_reconectador(sol, int(id_solenium), fecha_str)
        if curva_reconectador is not None and curva_reconectador.fillna(0).sum() > 0:
            return {
                "caso": 7, "energia_final_kwh": float(curva_reconectador.fillna(0).sum()),
                "curva_final": curva_reconectador, "medidor_usado": "reconectador",
                "revisar_manualmente": True,
            }

    crudos = datos_crudos.get_datos_crudos(gaia, node_ppal, fecha_str) if node_ppal else pd.DataFrame()

    if not datos_crudos.proyecto_generando(crudos):
        # Ya se intentó el reconectador arriba -- si llegamos acá es porque
        # no tenía nada (o no hay id_solenium). Último recurso antes de
        # confirmar apagado: sumar todos los inversores de Solenium /power/
        # e integrar. Se reporta DIRECTO, sin FP (no es "inversores vs
        # medidor", es la única lectura de generación disponible).
        if id_solenium is not None:
            resp_power = sol.get_power(int(id_solenium), fecha_str, fecha_str)
            curva_power, _ = solenium_svc.curva_de_power(resp_power)
            if curva_power.fillna(0).sum() > 0:
                return {
                    "caso": 7, "energia_final_kwh": float(curva_power.fillna(0).sum()),
                    "curva_final": curva_power, "medidor_usado": "solenium_power",
                    "revisar_manualmente": True,
                }
        # 0 kWh acá es la ausencia de CUALQUIER fuente (CGM, medidor,
        # inversores, reconectador, Solenium power) -- no una confirmación
        # real de que el proyecto está apagado. Un proyecto puede seguir
        # generando y que las 5 fuentes fallen el mismo día (real: San Diego
        # Sur 2026-08-03, sin medidor propio, solo vive de CGM -- si CGM no
        # responde ese día, no queda ninguna otra fuente). Marcar para
        # revisar en vez de reportar 0 con la misma confianza que un
        # apagado real y confirmado.
        return {
            "caso": 6, "energia_final_kwh": 0.0, "curva_final": CURVA_CERO.copy(),
            "medidor_usado": "ninguno", "revisar_manualmente": True,
        }

    if datos_crudos.datos_completos(crudos):
        total_riemann = datos_crudos.riemann_eae(crudos)
        return {
            "caso": 7, "energia_final_kwh": total_riemann,
            "curva_final": datos_crudos.curva_horaria_ap(crudos), "medidor_usado": "crudos",
        }

    # Caso 8: datos crudos incompletos -- se aprovechan las horas que sí
    # tienen cobertura real; el relleno centralizado (reconectador ->
    # Solenium × FP -> histórico) se encarga de completar lo que falte.
    curva_parcial = datos_crudos.curva_horaria_ap_con_huecos(crudos)
    return {
        "caso": 8, "energia_final_kwh": float(curva_parcial.fillna(0).sum()),
        "curva_final": curva_parcial, "medidor_usado": "crudos_parcial",
    }


def clasificar_generacion(
    db: Session,
    gaia: GaiaClient,
    sol: SoleniumClient,
    frontera_id: int,
    frt_code: str,
    border_meta: dict | None,
    project_id_solenium: int | None,
    mapa_medidor_nodo: dict[int, int],
    fecha: date,
) -> dict:
    """Clasifica una frontera de Generación para un día. Punto de entrada
    público -- puerto del bloque centralizado de clasificar() (repo
    Reporte-Energia), fusionado con _clasificar_fila() en una sola pasada
    por frontera.

    Retorna un dict listo para volcar en ReporteEnergiaGeneracion (columnas
    en snake_case, 'curva_final' como pd.Series[0..23]).
    """
    fecha_str = str(fecha)

    if frontera_id in FRONTERAS_TERCEROS:
        return {
            "caso": 0, "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
            "revisar_manualmente": True, "medidor_usado": "externo",
            "energia_cgm_kwh": None, "estado_reporte": None,
            "energia_solenium_kwh": None, "solenium_completo": None, "nota_solenium": None,
            "energia_medidor_principal_kwh": None, "energia_medidor_respaldo_kwh": None,
            "medidor_principal_completo": None, "medidor_respaldo_completo": None,
            "horas_rellenadas_reconectador": None, "horas_rellenadas_solenium": None,
            "horas_rellenadas_historico": None, "recuperacion_datos": None,
        }

    # --- CGM ---
    border_id = border_meta.get("border_id") if border_meta else None
    reporte = gaia.get_border_report_status(int(border_id), fecha_str) if border_id else None
    reporte_valido = bool(reporte) and str(reporte.get("status", "")).upper() in ESTADOS_AUTOMATICO
    estado_reporte = str(reporte.get("status")).upper() if reporte else None
    if reporte and reporte.get("reported_data_main"):
        curva_cgm = pd.Series(reporte["reported_data_main"][:24], index=HORAS, dtype=float)
    else:
        curva_cgm = CURVA_CERO.copy()
    e_cgm = float(curva_cgm.fillna(0).sum())

    # --- Medidor de nodo ---
    main_meter = border_meta.get("main_meter") if border_meta else None
    backup_meter = border_meta.get("backup_meter") if border_meta else None
    c = curvas.curvas_de_frontera(gaia, mapa_medidor_nodo, main_meter, backup_meter, fecha_str, frt_code)
    curva_ppal, curva_resp = c["curva_ppal"], c["curva_resp"]
    completo_ppal, completo_resp = c["ppal_completo"], c["resp_completo"]

    # --- Solenium (inversores) ---
    curva_solenium, solenium_completo = solenium_svc.curva_generacion(sol, project_id_solenium, fecha_str)
    e_inv_original = float(curva_solenium.fillna(0).sum())

    # Un hueco de telemetría en Solenium hace que e_inv_original sea un total
    # parcial -- de acá en adelante Solenium ya no es confiable para validar
    # cruzado, se trata como si no hubiera inversores en absoluto (e_inv=0)
    # para caer en la misma cadena de respaldo (CGM -> medidor -> datos
    # crudos). El total parcial se guarda aparte (e_inv_incompleto) por si
    # no hay ninguna otra fuente más -- ver Caso 5 y Casos 6/7/8 en
    # _decidir_caso.
    e_inv = e_inv_original
    e_inv_incompleto = None
    if e_inv > 0 and not solenium_completo:
        e_inv_incompleto = e_inv
        e_inv = 0.0

    resultado = _decidir_caso(
        db, frontera_id, fecha, fecha_str,
        e_cgm, curva_cgm, reporte_valido,
        curva_ppal, curva_resp, completo_ppal, completo_resp,
        e_inv, e_inv_incompleto, curva_solenium,
        project_id_solenium, c["node_ppal"], gaia, sol,
    )
    revisar = resultado.get("revisar_manualmente", False)

    # Un hueco de telemetría en Solenium marca revisión manual (no hay forma
    # de recuperarlo como con los medidores) -- excepto Caso 1, que no
    # depende de Solenium para nada (e_cgm ya avalado por Quoia).
    if resultado["caso"] != 1 and e_inv_original > 0 and not solenium_completo:
        revisar = True

    # --- Relleno horario centralizado ---
    curva_actual = resultado.get("curva_final")
    horas_reconectador, horas_solenium_h, horas_historico = set(), set(), set()
    if (
        resultado["caso"] in CASOS_CON_RELLENO_HORARIO
        and isinstance(curva_actual, pd.Series)
        and curva_actual.isna().any()
    ):
        if resultado.get("fp") is not None:
            fp_relleno, fp_calc_relleno = resultado["fp"], resultado.get("fp_calculada")
        else:
            fp_relleno, fp_calc_relleno = historial.get_factor_perdida_detalle(db, frontera_id, fecha)

        curva_rellenada, horas_reconectador, horas_solenium_h, horas_historico = reconectador.rellenar_horas_faltantes(
            db, sol, curva_actual, project_id_solenium, fecha_str,
            frontera_id=frontera_id,
            curva_solenium=curva_solenium if isinstance(curva_solenium, pd.Series) else None,
            fp=fp_relleno,
        )
        if horas_reconectador or horas_solenium_h or horas_historico:
            resultado["curva_final"] = curva_rellenada
            resultado["energia_final_kwh"] = float(curva_rellenada.fillna(0).sum())
        if horas_solenium_h and resultado.get("fp") is None:
            resultado["fp"] = round(fp_relleno, 4) if fp_relleno is not None else None
            resultado["fp_calculada"] = round(fp_calc_relleno, 4) if fp_calc_relleno is not None else None

        # Mismo caso de Villanueva/Paz Verso: un relleno vía reconectador o
        # Solenium × FP no es tan confiable como para darlo por bueno en
        # silencio, aunque haya tapado TODOS los huecos -- la API de
        # Solenium tiene un número limitado de consultas y puede no traer
        # la hora aunque Fusion sí la tenga completa. El histórico propio
        # no depende de ninguna API externa, así que ese no aplica.
        if horas_reconectador or horas_solenium_h:
            revisar = True
        if curva_rellenada.isna().any():
            revisar = True

        # medidor_usado='revisar' es el valor "no se pudo construir nada"
        # que puso _decidir_caso() para una curva vacía -- si el relleno de
        # arriba SÍ logró llenar horas (aunque no todas), ya no es cierto
        # que no haya fuente: quedaría diciendo "Sin fuente" con una energía
        # real y un FP calculado (ver Granja Solar Uruaco 2026-08-03: caso 3,
        # medidor_usado seguía en 'revisar' con 4.595,53 kWh reconstruidos
        # vía Solenium × FP en horas_rellenadas_solenium).
        if resultado.get("medidor_usado") == "revisar" and (horas_reconectador or horas_solenium_h or horas_historico):
            resultado["medidor_usado"] = "relleno_horario"

    resultado["revisar_manualmente"] = revisar
    resultado["horas_rellenadas_reconectador"] = sorted(horas_reconectador) or None
    resultado["horas_rellenadas_solenium"] = sorted(horas_solenium_h) or None
    resultado["horas_rellenadas_historico"] = sorted(horas_historico) or None
    resultado["energia_cgm_kwh"] = e_cgm
    resultado["estado_reporte"] = estado_reporte
    resultado["energia_solenium_kwh"] = e_inv_original
    resultado["solenium_completo"] = bool(solenium_completo)
    resultado["nota_solenium"] = "Sin registro en API Solenium" if project_id_solenium is None else None
    resultado["energia_medidor_principal_kwh"] = float(curva_ppal.fillna(0).sum())
    resultado["energia_medidor_respaldo_kwh"] = float(curva_resp.fillna(0).sum())
    resultado["medidor_principal_completo"] = bool(completo_ppal)
    resultado["medidor_respaldo_completo"] = bool(completo_resp)
    resultado["recuperacion_datos"] = c.get("recuperacion_datos")
    resultado.setdefault("fp", None)
    resultado.setdefault("fp_calculada", None)
    resultado.setdefault("error_final_pct", None)
    return resultado
