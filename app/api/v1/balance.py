"""Módulo Balance Energético.

Endpoint principal: GET /balance?start_date=&end_date=

Consolida en un balance mensual la energía del portafolio a partir de las tablas
que YA existen en la base (no hay tabla de "movimientos de energía"; las columnas
que asumía la idea original — fronteras.tipo_movimiento, generacion.energia_mwh,
etc. — no existen). El mapeo real usado es:

  * Generación real     → SUM(generacion_diaria.kwh_real) / 1000  (misma fuente
                          que el KPI de /dashboard).
  * Compromiso PPA      → SUM(ppa_compromisos_energia.energia_minima), el mínimo
                          contractual que se debe entregar ese mes (ya en MWh).
  * Consumo de clientes → SUM(fronteras_lecturas.energia_activa_import_kwh)/1000
                          para fronteras de tipo 'consumo'.
  * Venta neta en bolsa → SUM(export − import)/1000 en fronteras de generación
                          (energía entregada a la red menos la tomada de ella).
  * Precio de bolsa     → AVG(precios_bolsa_diario.precio_promedio) por mes.

Por cada mes: superavit_mwh = (generacion_real + venta_bolsa) − (compromiso_ppa +
consumo_clientes), y el estado (SUPERAVIT / DEFICIT / NEUTRO). El resumen agrega
los totales YTD (meses con generación registrada) y proyecta el balance a fin de
año de forma lineal sobre el promedio mensual observado.

Las funciones de cálculo (_iter_periods, _superavit_y_estado, _proyeccion_fin_anio
y build_balance) son puras y testeables sin base de datos.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import extract, func, text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.generacion import GeneracionDiaria
from app.models.contratos import PPACompromisoEnergia
from app.models.fronteras import Frontera, FronteraLectura, TipoFronteraEnum
from app.schemas.balance import BalanceResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/balance", tags=["Balance Energético"])

# Umbral (MWh) por debajo del cual un mes se considera NEUTRO en vez de
# SUPERAVIT/DEFICIT — evita clasificar como déficit un descuadre de redondeo.
_EPSILON = 0.001


# ── Núcleo de cálculo (puro, testeable) ───────────────────────────────────────

def _ym_key(y, m) -> tuple[int, int]:
    """Normaliza una clave (año, mes) a ints (EXTRACT devuelve Decimal/float)."""
    return (int(y), int(m))


def _iter_periods(start_date: date, end_date: date) -> list[tuple[int, int]]:
    """Lista de (año, mes) desde el mes de start_date hasta el de end_date, ambos
    inclusive."""
    periods: list[tuple[int, int]] = []
    y, m = start_date.year, start_date.month
    while (y, m) <= (end_date.year, end_date.month):
        periods.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return periods


def _superavit_y_estado(gen: float, ppa: float, consumo: float, bolsa: float):
    """(superavit_mwh, estado) de un mes.

    superavit = (generación + venta bolsa) − (compromiso PPA + consumo clientes).
    """
    superavit = round((gen + bolsa) - (ppa + consumo), 3)
    if superavit > _EPSILON:
        estado = "SUPERAVIT"
    elif superavit < -_EPSILON:
        estado = "DEFICIT"
    else:
        estado = "NEUTRO"
    return superavit, estado


def _proyeccion_fin_anio(balance_acumulado: float, meses_con_datos: int) -> float | None:
    """Proyección lineal del balance a fin de año: promedio mensual YTD × 12.

    Devuelve None si aún no hay meses con datos sobre los cuales promediar.
    """
    if meses_con_datos <= 0:
        return None
    return round(balance_acumulado / meses_con_datos * 12, 3)


def build_balance(
    start_date: date,
    end_date: date,
    gen_map: dict,
    ppa_map: dict,
    consumo_map: dict,
    bolsa_map: dict,
    precio_map: dict,
) -> dict:
    """Ensambla la respuesta a partir de los agregados mensuales ya calculados.

    Cada ``*_map`` está indexado por (año, mes). El resumen YTD y la proyección se
    calculan solo sobre los meses con generación registrada (``gen_map``), que son
    los meses efectivamente transcurridos con dato — un mes futuro con solo
    compromiso PPA no debe arrastrar el promedio.
    """
    meses = []
    for (y, m) in _iter_periods(start_date, end_date):
        gen = gen_map.get((y, m), 0.0)
        ppa = ppa_map.get((y, m), 0.0)
        consumo = consumo_map.get((y, m), 0.0)
        bolsa = bolsa_map.get((y, m), 0.0)
        precio = precio_map.get((y, m))
        superavit, estado = _superavit_y_estado(gen, ppa, consumo, bolsa)
        meses.append({
            "anio": y,
            "mes": m,
            "generacion_real_mwh": round(gen, 3),
            "compromiso_ppa_mwh": round(ppa, 3),
            "consumo_clientes_mwh": round(consumo, 3),
            "venta_bolsa_mwh": round(bolsa, 3),
            "precio_bolsa_promedio": round(precio, 2) if precio is not None else None,
            "superavit_mwh": superavit,
            "estado": estado,
        })

    realizados = [x for x in meses if (x["anio"], x["mes"]) in gen_map]
    n = len(realizados)
    balance_acumulado = round(sum(x["superavit_mwh"] for x in realizados), 3)
    resumen = {
        "generacion_total_mwh": round(sum(x["generacion_real_mwh"] for x in realizados), 3),
        "compromiso_ppa_total_mwh": round(sum(x["compromiso_ppa_mwh"] for x in realizados), 3),
        "consumo_clientes_total_mwh": round(sum(x["consumo_clientes_mwh"] for x in realizados), 3),
        "venta_bolsa_total_mwh": round(sum(x["venta_bolsa_mwh"] for x in realizados), 3),
        "balance_acumulado_mwh": balance_acumulado,
        "proyeccion_fin_anio_mwh": _proyeccion_fin_anio(balance_acumulado, n),
        "meses_con_datos": n,
    }
    return {
        "start_date": start_date,
        "end_date": end_date,
        "resumen": resumen,
        "meses": meses,
    }


# ── Agregados mensuales desde la base ──────────────────────────────────────────

def _generacion_map(db: Session, start_date: date, end_date: date) -> dict:
    """MWh generados por mes desde generacion_diaria (kwh_real / 1000)."""
    rows = (
        db.query(
            extract("year", GeneracionDiaria.fecha).label("y"),
            extract("month", GeneracionDiaria.fecha).label("m"),
            func.sum(GeneracionDiaria.kwh_real).label("kwh"),
        )
        .filter(
            GeneracionDiaria.fecha >= start_date,
            GeneracionDiaria.fecha <= end_date,
        )
        .group_by(
            extract("year", GeneracionDiaria.fecha),
            extract("month", GeneracionDiaria.fecha),
        )
        .all()
    )
    return {
        _ym_key(r.y, r.m): round(float(r.kwh) / 1000, 3)
        for r in rows if r.kwh is not None
    }


def _compromiso_ppa_map(db: Session, start_date: date, end_date: date) -> dict:
    """MWh de compromiso PPA (energía mínima) por mes.

    Filtra por rango de años; los meses fuera del rango pedido no se usan porque
    build_balance solo consulta los (año, mes) del período.
    """
    rows = (
        db.query(
            PPACompromisoEnergia.año.label("y"),
            PPACompromisoEnergia.mes.label("m"),
            func.sum(PPACompromisoEnergia.energia_minima).label("mwh"),
        )
        .filter(
            PPACompromisoEnergia.año >= start_date.year,
            PPACompromisoEnergia.año <= end_date.year,
        )
        .group_by(PPACompromisoEnergia.año, PPACompromisoEnergia.mes)
        .all()
    )
    return {
        _ym_key(r.y, r.m): round(float(r.mwh), 3)
        for r in rows if r.mwh is not None
    }


def _consumo_clientes_map(db: Session, start_date: date, end_date: date) -> dict:
    """MWh consumidos por clientes: import de fronteras de tipo 'consumo'."""
    rows = (
        db.query(
            extract("year", FronteraLectura.periodo_inicio).label("y"),
            extract("month", FronteraLectura.periodo_inicio).label("m"),
            func.sum(FronteraLectura.energia_activa_import_kwh).label("kwh"),
        )
        .join(Frontera, FronteraLectura.frontera_id == Frontera.id)
        .filter(
            Frontera.tipo_frontera == TipoFronteraEnum.consumo,
            Frontera.deleted_at.is_(None),
            FronteraLectura.periodo_inicio >= start_date,
            FronteraLectura.periodo_inicio <= end_date,
        )
        .group_by(
            extract("year", FronteraLectura.periodo_inicio),
            extract("month", FronteraLectura.periodo_inicio),
        )
        .all()
    )
    return {
        _ym_key(r.y, r.m): round(float(r.kwh) / 1000, 3)
        for r in rows if r.kwh is not None
    }


def _venta_bolsa_map(db: Session, start_date: date, end_date: date) -> dict:
    """Posición neta en bolsa (MWh): export − import en fronteras de generación."""
    rows = (
        db.query(
            extract("year", FronteraLectura.periodo_inicio).label("y"),
            extract("month", FronteraLectura.periodo_inicio).label("m"),
            func.sum(FronteraLectura.energia_activa_export_kwh).label("exp"),
            func.sum(FronteraLectura.energia_activa_import_kwh).label("imp"),
        )
        .join(Frontera, FronteraLectura.frontera_id == Frontera.id)
        .filter(
            Frontera.tipo_frontera.in_([
                TipoFronteraEnum.generacion,
                TipoFronteraEnum.generacion_consumo,
            ]),
            Frontera.deleted_at.is_(None),
            FronteraLectura.periodo_inicio >= start_date,
            FronteraLectura.periodo_inicio <= end_date,
        )
        .group_by(
            extract("year", FronteraLectura.periodo_inicio),
            extract("month", FronteraLectura.periodo_inicio),
        )
        .all()
    )
    return {
        _ym_key(r.y, r.m): round((float(r.exp or 0) - float(r.imp or 0)) / 1000, 3)
        for r in rows
    }


def _precio_bolsa_map(db: Session, start_date: date, end_date: date) -> dict:
    """Precio de bolsa promedio por mes desde precios_bolsa_diario (raw SQL: la
    tabla no tiene modelo ORM — mismo acceso que /cumplimiento y /dashboard)."""
    rows = db.execute(text("""
        SELECT EXTRACT(YEAR FROM fecha) AS y,
               EXTRACT(MONTH FROM fecha) AS m,
               AVG(precio_promedio) AS precio
        FROM precios_bolsa_diario
        WHERE fecha >= :start AND fecha <= :end
          AND precio_promedio IS NOT NULL
        GROUP BY 1, 2
    """), {"start": start_date, "end": end_date}).fetchall()
    return {
        _ym_key(r.y, r.m): float(r.precio)
        for r in rows if r.precio is not None
    }


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("", response_model=BalanceResponse)
def get_balance_energetico(
    start_date: date | None = Query(None, description="Inicio del rango (default: 1-ene del año actual)"),
    end_date: date | None = Query(None, description="Fin del rango (default: 31-dic del año actual)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Balance energético mensual consolidado + resumen YTD y proyección."""
    today = date.today()
    if start_date is None:
        start_date = date(today.year, 1, 1)
    if end_date is None:
        end_date = date(today.year, 12, 31)
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date debe ser mayor o igual a start_date")

    data = build_balance(
        start_date,
        end_date,
        _generacion_map(db, start_date, end_date),
        _compromiso_ppa_map(db, start_date, end_date),
        _consumo_clientes_map(db, start_date, end_date),
        _venta_bolsa_map(db, start_date, end_date),
        _precio_bolsa_map(db, start_date, end_date),
    )
    return BalanceResponse(**data)
