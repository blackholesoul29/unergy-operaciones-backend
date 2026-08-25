"""Histórico propio de cada frontera -- factor de pérdida, mediana y forma
horaria -- consultando directamente las tablas de reporte ya guardadas en
Postgres (reporte_energia_generacion / reporte_energia_consumo) en vez de
los CSV que usaba el pipeline original (Reporte-Energia).

Puerto de estimacion.py + historial_horario_generacion.py + partes de
estimacion_consumo.py.
"""
from __future__ import annotations

import random
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.services.reporte_energia.utils import lista_a_curva

MIN_DIAS_FP      = 3    # mínimo de días con datos para calcular el factor de pérdida
MIN_DIAS_FORMA   = 3    # mínimo de días con reporte confiable antes de usar mediana/forma
MIN_DIAS_CONSUMO = 3
DIAS_VENTANA     = 30

# Casos de Generación cuya curva se considera dato real y completo, apto
# para alimentar mediana/forma -- Caso 3 (estimado vía FP) y Caso 8 (crudos
# parciales) quedan fuera a propósito, igual que Caso 6 (apagado) y 0 (externo).
CASOS_CONFIABLES_GENERACION = {1, 2, 4, 5, 7}

# Fronteras con FP fijo (decidido, no calculado del histórico) -- para
# medidores crónicamente inestables donde el ratio E_med/E_inv no refleja
# pérdida física real. Clave: frontera_id. Confirmar el id real contra la
# BD antes de usar en producción (0.99 para "MGS 0028 COX - Chiriguaná
# Norte 1" en el pipeline original, Reporte-Energia).
FP_FIJO: dict[int, float] = {}

UMBRAL_FP_MUY_BAJO  = 0.9
# Sin FP calculable del histórico, se reporta un valor variado día a día
# dentro de este rango en vez de repetir siempre el mismo número fijo
# (decisión de negocio, 2026-08-19) -- determinístico por frontera+fecha
# (ver _fp_fallback) para que no cambie si se re-consulta o se re-corre el
# mismo día.
FP_FALLBACK_RANGO = (0.990, 0.995)


def _fp_fallback(frontera_id: int, fecha: date) -> float:
    rng = random.Random(f"{frontera_id}:{fecha.isoformat()}")
    lo, hi = FP_FALLBACK_RANGO
    return round(rng.uniform(lo, hi), 4)

# Fronteras de Consumo sin telemedida propia que comparten predio físico con
# otra frontera que sí reporta con normalidad -- para el Caso 'Histórico' de
# consumo, se usa el histórico del vecino en vez de rendirse en 'Sin dato'.
# Clave/valor: frontera_id. Confirmar los ids reales contra la BD antes de
# usar en producción ("MGS 0033 - Sabana de Torres" -> "MGS 0012 - La
# Reserva" en el pipeline original).
VECINO_HISTORICO_CONSUMO: dict[int, int] = {}


# ---------------------------------------------------------------------------
# Factor de pérdida (Generación)
# ---------------------------------------------------------------------------

def get_factor_perdida_detalle(db: Session, frontera_id: int, fecha: date) -> tuple[float | None, float | None]:
    """Retorna (fp_usado, fp_calculado) para una frontera de Generación.

    fp_calculado: mediana de los ratios diarios (E_med/E_inv) de los últimos
    DIAS_VENTANA días ANTES de `fecha`, con medidor completo ese día y ambas
    energías > 0 -- independiente de qué Caso ganó ese día (un día Caso 3 no
    aporta, porque su 'energia_final_kwh' ya sale de invertir el propio FP).

    fp_usado: lo que realmente se aplica -- FP_FIJO si la frontera está ahí,
    un valor dentro de FP_FALLBACK_RANGO (variado por frontera+fecha, ver
    _fp_fallback) si fp_calculado < UMBRAL_FP_MUY_BAJO o no hay histórico
    suficiente, o fp_calculado tal cual en el resto de los casos.
    """
    filas = db.execute(
        select(
            ReporteEnergiaGeneracion.energia_medidor_principal_kwh,
            ReporteEnergiaGeneracion.energia_medidor_respaldo_kwh,
            ReporteEnergiaGeneracion.medidor_principal_completo,
            ReporteEnergiaGeneracion.medidor_respaldo_completo,
            ReporteEnergiaGeneracion.energia_solenium_kwh,
        )
        .where(
            ReporteEnergiaGeneracion.frontera_id == frontera_id,
            ReporteEnergiaGeneracion.fecha < fecha,
        )
        .order_by(ReporteEnergiaGeneracion.fecha.desc())
        .limit(DIAS_VENTANA)
    ).all()

    ratios = []
    for e_ppal, e_resp, comp_ppal, comp_resp, e_inv in filas:
        e_inv = float(e_inv or 0)
        if e_inv <= 0:
            continue
        usar_ppal = bool(e_ppal and float(e_ppal) > 0)
        e_med = float(e_ppal or 0) if usar_ppal else float(e_resp or 0)
        completo = bool(comp_ppal) if usar_ppal else bool(comp_resp)
        if e_med > 0 and completo:
            ratios.append(e_med / e_inv)

    fp_calculado = float(pd.Series(ratios).median()) if len(ratios) >= MIN_DIAS_FP else None

    if frontera_id in FP_FIJO:
        return FP_FIJO[frontera_id], fp_calculado

    if fp_calculado is None:
        return _fp_fallback(frontera_id, fecha), None

    if fp_calculado < UMBRAL_FP_MUY_BAJO:
        return _fp_fallback(frontera_id, fecha), fp_calculado

    return fp_calculado, fp_calculado


# ---------------------------------------------------------------------------
# Mediana / forma horaria -- Generación
# ---------------------------------------------------------------------------

def get_mediana_generacion(db: Session, frontera_id: int, fecha: date) -> tuple[float | None, int]:
    """Mediana del total diario de los últimos DIAS_VENTANA días con Caso
    confiable Y sin revisión manual, ANTES de `fecha`."""
    totales = db.execute(
        select(ReporteEnergiaGeneracion.energia_final_kwh)
        .where(
            ReporteEnergiaGeneracion.frontera_id == frontera_id,
            ReporteEnergiaGeneracion.fecha < fecha,
            ReporteEnergiaGeneracion.caso.in_(CASOS_CONFIABLES_GENERACION),
            ReporteEnergiaGeneracion.revisar_manualmente.is_(False),
        )
        .order_by(ReporteEnergiaGeneracion.fecha.desc())
        .limit(DIAS_VENTANA)
    ).scalars().all()

    # energia_final_kwh puede ser NULL incluso en un Caso "confiable" (ej. un
    # registro editado a mano a medias, o un dato viejo previo a que el
    # clasificador siempre lo llenara) -- float(None) tumbaba toda la corrida
    # del dia (ver ejecutar_dia, sin try/except por frontera).
    validos = [float(t) for t in totales if t is not None]
    if len(validos) < MIN_DIAS_FORMA:
        return None, len(validos)
    return float(pd.Series(validos).median()), len(validos)


def get_forma_generacion(db: Session, frontera_id: int, fecha: date) -> tuple[pd.Series | None, int]:
    """Forma horaria típica (24 valores) de los últimos DIAS_VENTANA días con
    Caso confiable, sin revisión manual y curva completa (sin huecos), ANTES
    de `fecha`. Cada día se normaliza a su propio total antes de combinarlos;
    se toma la MEDIANA por hora entre esos días normalizados.

    Retorna (forma, dias_usados). forma NO suma necesariamente 1 -- reescalar
    al total real con utils.escalar_curva(). None si hay menos de
    MIN_DIAS_FORMA días disponibles.
    """
    curvas = db.execute(
        select(ReporteEnergiaGeneracion.curva_final)
        .where(
            ReporteEnergiaGeneracion.frontera_id == frontera_id,
            ReporteEnergiaGeneracion.fecha < fecha,
            ReporteEnergiaGeneracion.caso.in_(CASOS_CONFIABLES_GENERACION),
            ReporteEnergiaGeneracion.revisar_manualmente.is_(False),
        )
        .order_by(ReporteEnergiaGeneracion.fecha.desc())
        .limit(DIAS_VENTANA)
    ).scalars().all()

    formas = []
    for valores in curvas:
        curva = lista_a_curva(valores)
        if curva.isna().any():
            continue  # día con huecos -- no aporta a la forma
        total = curva.sum()
        if total > 0:
            formas.append(curva / total)

    if len(formas) < MIN_DIAS_FORMA:
        return None, len(formas)

    forma_mediana = pd.concat(formas, axis=1).median(axis=1)
    return forma_mediana, len(formas)


# ---------------------------------------------------------------------------
# Mediana / forma horaria -- Consumo
# ---------------------------------------------------------------------------

CASOS_CONFIABLES_CONSUMO = ("Medidor", "CGM")


def get_mediana_consumo(db: Session, frontera_id: int, fecha: date) -> tuple[float | None, int]:
    """Mediana del total diario de los últimos DIAS_VENTANA días de Caso
    'Medidor' o 'CGM' sin revisión manual, ANTES de `fecha`. 'Histórico'
    queda fuera (es ya una estimación, no lectura real). 'CGM' cuenta como
    confiable porque el reporte automático de Quoia es en sí una lectura
    real (ASIC), no una estimación -- salvo fronteras en
    FRONTERAS_VALIDAR_CGM_VS_MEDIDOR (ej. Paso Norte), que SIEMPRE quedan
    con revisar_manualmente=True (ver clasificador_consumo.py) y por lo
    tanto nunca entran acá, aunque el cruce contra medidor haya pasado ese
    día puntual -- el bug de Quoia es intermitente.

    Sin este 'CGM', ninguna frontera de Consumo podría nunca construir
    historial desde cero: 'Medidor' sin mediana previa SIEMPRE queda
    revisar_manualmente=True (no hay una segunda fuente independiente tipo
    inversores, como sí tiene Generación, para autoconfirmarse el mismo
    día) -- sin 'Validar Frontera' a mano en cada frontera, el filtro nunca
    se llenaría."""
    totales = db.execute(
        select(ReporteEnergiaConsumo.energia_final_kwh)
        .where(
            ReporteEnergiaConsumo.frontera_id == frontera_id,
            ReporteEnergiaConsumo.fecha < fecha,
            ReporteEnergiaConsumo.caso.in_(CASOS_CONFIABLES_CONSUMO),
            ReporteEnergiaConsumo.revisar_manualmente.is_(False),
        )
        .order_by(ReporteEnergiaConsumo.fecha.desc())
        .limit(DIAS_VENTANA)
    ).scalars().all()

    validos = [float(t) for t in totales if t is not None]
    if len(validos) < MIN_DIAS_CONSUMO:
        return None, len(validos)
    return float(pd.Series(validos).median()), len(validos)


def get_forma_consumo(db: Session, frontera_id: int, fecha: date) -> tuple[pd.Series | None, int]:
    """Forma horaria típica de Consumo, mismo criterio que get_mediana_consumo
    (Caso 'Medidor' o 'CGM' sin revisión manual)."""
    curvas = db.execute(
        select(ReporteEnergiaConsumo.curva_final)
        .where(
            ReporteEnergiaConsumo.frontera_id == frontera_id,
            ReporteEnergiaConsumo.fecha < fecha,
            ReporteEnergiaConsumo.caso.in_(CASOS_CONFIABLES_CONSUMO),
            ReporteEnergiaConsumo.revisar_manualmente.is_(False),
        )
        .order_by(ReporteEnergiaConsumo.fecha.desc())
        .limit(DIAS_VENTANA)
    ).scalars().all()

    formas = []
    for valores in curvas:
        curva = lista_a_curva(valores)
        if curva.isna().any():
            continue
        total = curva.sum()
        if total > 0:
            formas.append(curva / total)

    if len(formas) < MIN_DIAS_CONSUMO:
        return None, len(formas)

    forma_mediana = pd.concat(formas, axis=1).median(axis=1)
    return forma_mediana, len(formas)
