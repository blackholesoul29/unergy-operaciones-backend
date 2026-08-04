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
                     dato real -- se confía en él a ciegas.
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

    if reporte_valido and e_cgm > 0:
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
            # Sin mediana historica para comparar -- si al menos un medidor
            # trae las 24 horas COMPLETAS (sin huecos que pudieran armar un
            # pico artificial, ver docstring del modulo), no tiene sentido
            # descartarlo solo porque no hay con que cruzarlo. Se reporta
            # igual (mayor valor si ambos estan completos, mismo criterio que
            # ya usa clasificador.py cuando no hay CGM/inversores), marcado
            # para revisar a mano porque nadie confirmo que el nivel sea
            # el correcto.
            ppal_completo = curva_ppal.notna().all()
            resp_completo = curva_resp.notna().all()
            if ppal_completo or resp_completo:
                if ppal_completo and resp_completo:
                    usar_ppal = curva_ppal.fillna(0).sum() >= curva_resp.fillna(0).sum()
                else:
                    usar_ppal = ppal_completo
                curva = curva_ppal if usar_ppal else curva_resp
                medidor_usado = "principal_sin_historico" if usar_ppal else "respaldo_sin_historico"
                return {
                    "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                    "medidor_usado": medidor_usado, "revisar_manualmente": True,
                    "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                    "recuperacion_datos": recuperacion_datos,
                }
            return {
                "caso": "Medidor", "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
                "medidor_usado": "revisar", "revisar_manualmente": True,
                "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                "recuperacion_datos": recuperacion_datos,
            }
    elif tiene_ppal or tiene_resp:
        curva = curva_ppal if tiene_ppal else curva_resp
        if mediana is None:
            if curva.notna().all():
                return {
                    "caso": "Medidor", "energia_final_kwh": float(curva.fillna(0).sum()), "curva_final": curva,
                    "medidor_usado": "principal_sin_historico" if tiene_ppal else "respaldo_sin_historico",
                    "revisar_manualmente": True,
                    "energia_cgm_kwh": e_cgm, "estado_reporte": estado_reporte,
                    "recuperacion_datos": recuperacion_datos,
                }
            return {
                "caso": "Medidor", "energia_final_kwh": None, "curva_final": CURVA_VACIA.copy(),
                "medidor_usado": "revisar", "revisar_manualmente": True,
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
