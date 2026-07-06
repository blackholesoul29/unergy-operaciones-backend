"""Lógica del módulo Descubrimientos y Gestión de Riesgos de Bolsa.

Contiene tanto las operaciones CRUD sobre `PrecioBolsa` como el cálculo de
exposición financiera e indicadores de riesgo.

Modelo de exposición
---------------------
    exposición_cop = (generación_mwh − obligación_ppa_mwh) × precio_bolsa_cop_mwh

* Excedente (generación > obligación) → exposición positiva: energía que se
  vende en bolsa.
* Déficit (generación < obligación) → exposición negativa: energía que se debe
  comprar en bolsa para cubrir el PPA.

Granularidad: la generación (`generacion_diaria`) es diaria y los compromisos
PPA (`ppa_compromisos_energia`) son mensuales, mientras que el precio de bolsa
es horario. El cálculo se hace por lo tanto a nivel **diario**: el precio se
promedia por día, la generación se suma por día (kWh→MWh) y la obligación
mensual se prorratea entre los días del mes.
"""
import calendar
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.riesgos_bolsa import PrecioBolsa
from app.models.generacion import GeneracionDiaria
from app.models.contratos import (
    PPAContrato, PPACompromisoEnergia, ppa_contrato_proyectos_table,
)


# ── Núcleo puro (sin BD) ────────────────────────────────────────────────────

def compute_exposure(generacion_mwh, ppa_obligacion_mwh, precio_cop_mwh):
    """Exposición en COP para un punto. Devuelve None si falta cualquier dato."""
    if generacion_mwh is None or ppa_obligacion_mwh is None or precio_cop_mwh is None:
        return None
    delta = float(generacion_mwh) - float(ppa_obligacion_mwh)
    return round(delta * float(precio_cop_mwh), 2)


def _percentile(valores: list[float], pct: float) -> float:
    """Percentil por interpolación lineal (pct en 0..100)."""
    if not valores:
        return 0.0
    orden = sorted(valores)
    if len(orden) == 1:
        return orden[0]
    rango = (pct / 100.0) * (len(orden) - 1)
    bajo = int(rango)
    alto = min(bajo + 1, len(orden) - 1)
    frac = rango - bajo
    return orden[bajo] + (orden[alto] - orden[bajo]) * frac


def compute_risk_indicators(exposures) -> dict:
    """Indicadores de riesgo sobre una serie de exposiciones (COP).

    VaR 95% = percentil 5 de la distribución de exposición: el peor escenario
    con 95% de confianza (valor bajo/negativo = mayor pérdida esperada).
    """
    vals = [float(x) for x in exposures if x is not None]
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "exposicion_total_cop": 0.0,
            "exposicion_media_cop": None,
            "exposicion_std_cop": None,
            "exposicion_max_cop": None,
            "exposicion_min_cop": None,
            "var_95_cop": None,
        }
    return {
        "n": n,
        "exposicion_total_cop": round(sum(vals), 2),
        "exposicion_media_cop": round(statistics.mean(vals), 2),
        "exposicion_std_cop": round(statistics.stdev(vals), 2) if n > 1 else 0.0,
        "exposicion_max_cop": round(max(vals), 2),
        "exposicion_min_cop": round(min(vals), 2),
        "var_95_cop": round(_percentile(vals, 5), 2),
    }


def project_exposure_scenario(
    precio_bolsa_forecast: dict,
    generacion_forecast: dict | None = None,
    ppa_obligations: dict | None = None,
) -> dict:
    """Proyecta exposición para un escenario de pronósticos.

    Cada argumento es un dict `{fecha: valor}` (fecha = date). Se itera sobre
    las fechas presentes en `precio_bolsa_forecast`; generación y obligación
    ausentes para una fecha se toman como 0.

    Devuelve `{"puntos": [...], "indicadores": {...}}`.
    """
    generacion_forecast = generacion_forecast or {}
    ppa_obligations = ppa_obligations or {}

    puntos = []
    for fecha in sorted(precio_bolsa_forecast):
        precio = precio_bolsa_forecast[fecha]
        gen = generacion_forecast.get(fecha, 0.0)
        obl = ppa_obligations.get(fecha, 0.0)
        exposicion = compute_exposure(gen, obl, precio)
        puntos.append(
            {
                "fecha": fecha,
                "generacion_mwh": None if gen is None else float(gen),
                "ppa_obligacion_mwh": None if obl is None else float(obl),
                "precio_cop_mwh": None if precio is None else float(precio),
                "exposicion_cop": exposicion,
            }
        )
    indicadores = compute_risk_indicators([p["exposicion_cop"] for p in puntos])
    return {"puntos": puntos, "indicadores": indicadores}


# ── CRUD de PrecioBolsa ─────────────────────────────────────────────────────

def create_precio_bolsa_entry(db: Session, data: dict) -> PrecioBolsa:
    row = PrecioBolsa(
        fecha_hora=data["fecha_hora"],
        precio_cop_mwh=data["precio_cop_mwh"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_precio_bolsa_by_datetime(db: Session, fecha_hora: datetime) -> PrecioBolsa | None:
    return db.query(PrecioBolsa).filter(PrecioBolsa.fecha_hora == fecha_hora).first()


def get_precio_bolsa_range(
    db: Session, start_dt: datetime, end_dt: datetime
) -> list[PrecioBolsa]:
    return (
        db.query(PrecioBolsa)
        .filter(PrecioBolsa.fecha_hora >= start_dt, PrecioBolsa.fecha_hora <= end_dt)
        .order_by(PrecioBolsa.fecha_hora)
        .all()
    )


def bulk_upsert_precio_bolsa(db: Session, data_list: list[dict]) -> dict:
    """Inserta o actualiza (por fecha_hora) una lista de precios.

    Devuelve `{"insertados", "actualizados", "total_filas"}`.
    """
    insertados = actualizados = 0
    existentes = {
        row.fecha_hora: row
        for row in db.query(PrecioBolsa).filter(
            PrecioBolsa.fecha_hora.in_([d["fecha_hora"] for d in data_list])
        ).all()
    } if data_list else {}

    for d in data_list:
        fh = d["fecha_hora"]
        row = existentes.get(fh)
        if row is not None:
            row.precio_cop_mwh = d["precio_cop_mwh"]
            actualizados += 1
        else:
            row = PrecioBolsa(fecha_hora=fh, precio_cop_mwh=d["precio_cop_mwh"])
            db.add(row)
            existentes[fh] = row  # evita doble-insert si el lote tiene la misma hora repetida
            insertados += 1

    db.commit()
    return {
        "insertados": insertados,
        "actualizados": actualizados,
        "total_filas": len(data_list),
    }


# ── Agregaciones diarias desde la BD ────────────────────────────────────────

def get_precio_promedio_por_dia(
    db: Session, start_dt: date, end_dt: date
) -> dict[date, float]:
    """Precio de bolsa promedio (COP/MWh) por día en el rango."""
    inicio = datetime(start_dt.year, start_dt.month, start_dt.day)
    fin = datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59)
    dia_col = func.date(PrecioBolsa.fecha_hora)
    rows = (
        db.query(dia_col.label("dia"), func.avg(PrecioBolsa.precio_cop_mwh).label("prom"))
        .filter(PrecioBolsa.fecha_hora >= inicio, PrecioBolsa.fecha_hora <= fin)
        .group_by(dia_col)
        .all()
    )
    return {_as_date(r.dia): float(r.prom) for r in rows if r.prom is not None}


def get_generacion_mwh_por_dia(
    db: Session, start_dt: date, end_dt: date, planta_id: int | None = None
) -> dict[date, float]:
    """Generación real (MWh) por día; opcionalmente filtrada por proyecto."""
    q = (
        db.query(
            GeneracionDiaria.fecha.label("dia"),
            func.sum(GeneracionDiaria.kwh_real).label("kwh"),
        )
        .filter(GeneracionDiaria.fecha >= start_dt, GeneracionDiaria.fecha <= end_dt)
    )
    if planta_id is not None:
        q = q.filter(GeneracionDiaria.proyecto_id == planta_id)
    rows = q.group_by(GeneracionDiaria.fecha).all()
    return {r.dia: float(r.kwh) / 1000.0 for r in rows if r.kwh is not None}


def get_ppa_obligacion_mwh_por_dia(
    db: Session, start_dt: date, end_dt: date, planta_id: int | None = None
) -> dict[date, float]:
    """Obligación PPA (MWh) prorrateada por día.

    Suma `energia_minima` de los compromisos mensuales de contratos vigentes
    (deleted_at IS NULL) y reparte cada total mensual entre los días de su mes.
    Si se da `planta_id`, sólo cuenta contratos que incluyen esa planta.
    """
    # (año, mes) que toca el rango.
    meses = _meses_en_rango(start_dt, end_dt)
    if not meses:
        return {}

    q = (
        db.query(
            PPACompromisoEnergia.año.label("anio"),
            PPACompromisoEnergia.mes.label("mes"),
            func.sum(PPACompromisoEnergia.energia_minima).label("energia"),
        )
        .join(PPAContrato, PPAContrato.id == PPACompromisoEnergia.contrato_id)
        .filter(PPAContrato.deleted_at.is_(None))
    )
    if planta_id is not None:
        q = q.join(
            ppa_contrato_proyectos_table,
            ppa_contrato_proyectos_table.c.contrato_id == PPAContrato.id,
        ).filter(ppa_contrato_proyectos_table.c.proyecto_id == planta_id)

    condiciones = [
        (PPACompromisoEnergia.año == a) & (PPACompromisoEnergia.mes == m)
        for a, m in meses
    ]
    from functools import reduce
    from operator import or_ as _or
    q = q.filter(reduce(_or, condiciones))

    total_por_mes = {
        (r.anio, r.mes): float(r.energia)
        for r in q.group_by(PPACompromisoEnergia.año, PPACompromisoEnergia.mes).all()
        if r.energia is not None
    }

    resultado: dict[date, float] = {}
    dia = start_dt
    while dia <= end_dt:
        total_mes = total_por_mes.get((dia.year, dia.month))
        if total_mes is not None:
            dias_mes = calendar.monthrange(dia.year, dia.month)[1]
            resultado[dia] = total_mes / dias_mes
        dia += timedelta(days=1)
    return resultado


def get_historical_exposure(
    db: Session, start_dt: date, end_dt: date, planta_id: int | None = None
) -> dict:
    """Exposición histórica diaria en el rango. Devuelve puntos + indicadores."""
    precios = get_precio_promedio_por_dia(db, start_dt, end_dt)
    generaciones = get_generacion_mwh_por_dia(db, start_dt, end_dt, planta_id)
    obligaciones = get_ppa_obligacion_mwh_por_dia(db, start_dt, end_dt, planta_id)

    dias = sorted(set(precios) | set(generaciones) | set(obligaciones))
    puntos = []
    for dia in dias:
        precio = precios.get(dia)
        gen = generaciones.get(dia, 0.0)
        obl = obligaciones.get(dia, 0.0)
        exposicion = compute_exposure(gen, obl, precio)
        puntos.append(
            {
                "fecha": dia,
                "planta_id": planta_id,
                "generacion_mwh": gen,
                "ppa_obligacion_mwh": obl,
                "precio_cop_mwh": precio,
                "exposicion_cop": exposicion,
            }
        )
    indicadores = compute_risk_indicators([p["exposicion_cop"] for p in puntos])
    return {"puntos": puntos, "indicadores": indicadores}


def calculate_current_exposure(
    db: Session, fecha: date | None = None, planta_id: int | None = None
) -> dict:
    """Exposición del día `fecha` (o el último día con precio disponible)."""
    if fecha is None:
        ultimo = db.query(func.max(PrecioBolsa.fecha_hora)).scalar()
        if ultimo is None:
            return {
                "fecha": None,
                "planta_id": planta_id,
                "generacion_mwh": None,
                "ppa_obligacion_mwh": None,
                "precio_cop_mwh": None,
                "exposicion_cop": None,
            }
        fecha = _as_date(ultimo)

    resultado = get_historical_exposure(db, fecha, fecha, planta_id)
    if resultado["puntos"]:
        return resultado["puntos"][0]
    return {
        "fecha": fecha,
        "planta_id": planta_id,
        "generacion_mwh": None,
        "ppa_obligacion_mwh": None,
        "precio_cop_mwh": None,
        "exposicion_cop": None,
    }


def get_risk_indicators(
    db: Session, start_dt: date, end_dt: date, planta_id: int | None = None
) -> dict:
    """Indicadores de riesgo sobre la exposición diaria del rango."""
    historico = get_historical_exposure(db, start_dt, end_dt, planta_id)
    indicadores = historico["indicadores"]
    return {
        "start_dt": start_dt,
        "end_dt": end_dt,
        "planta_id": planta_id,
        **indicadores,
    }


# ── Utilidades ──────────────────────────────────────────────────────────────

def _as_date(valor) -> date:
    """func.date() devuelve date en Postgres pero str en SQLite."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()


def _meses_en_rango(start_dt: date, end_dt: date) -> list[tuple[int, int]]:
    meses = []
    a, m = start_dt.year, start_dt.month
    while (a, m) <= (end_dt.year, end_dt.month):
        meses.append((a, m))
        if m == 12:
            a, m = a + 1, 1
        else:
            m += 1
    return meses
