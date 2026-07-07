"""Tests del mapeo de precios de bolsa (`XMPriceMapper`).

Cubren la función pura de selección/fallback (`seleccionar_precio`) y el
comportamiento del mapper contra una sesión de BD simulada — incluyendo la
cadena de fallback (día → anterior → base), el promedio mensual y el caché que
evita consultas SQL redundantes. No tocan la BD real.
"""
from decimal import Decimal
from types import SimpleNamespace

from app.utils.xm_price_mapper import (
    FUENTE_BASE,
    FUENTE_DIARIO,
    FUENTE_FALLBACK,
    FUENTE_MES,
    FUENTE_NINGUNA,
    XMPriceMapper,
    seleccionar_precio,
)


# ── seleccionar_precio (pura) ────────────────────────────────────────────────
def test_selecciona_precio_del_dia_con_prioridad():
    r = seleccionar_precio(200, 180, 150)
    assert r.precio == Decimal("200") and r.fuente == FUENTE_DIARIO


def test_fallback_a_precio_anterior_si_no_hay_del_dia():
    r = seleccionar_precio(None, 180, 150)
    assert r.precio == Decimal("180") and r.fuente == FUENTE_FALLBACK


def test_fallback_a_precio_base_si_no_hay_datos_de_bolsa():
    r = seleccionar_precio(None, None, 150)
    assert r.precio == Decimal("150") and r.fuente == FUENTE_BASE


def test_sin_ningun_precio_disponible():
    r = seleccionar_precio(None, None, None)
    assert r.precio is None and r.fuente == FUENTE_NINGUNA


def test_precio_no_positivo_se_descarta():
    # 0 y negativos no son válidos → cae al siguiente candidato
    r = seleccionar_precio(0, -5, 150)
    assert r.precio == Decimal("150") and r.fuente == FUENTE_BASE


# ── XMPriceMapper con sesión simulada ────────────────────────────────────────
class _FakeExec:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeDB:
    """Sesión SQLAlchemy mínima: enruta por el texto del SQL."""

    def __init__(self, exacto=None, anterior=None, mes=None):
        self.exacto = exacto
        self.anterior = anterior
        self.mes = mes
        self.calls = 0

    def execute(self, stmt, params=None):
        self.calls += 1
        sql = str(stmt)
        if "AVG(precio_promedio)" in sql:
            return _FakeExec(SimpleNamespace(avg_precio=self.mes))
        if "fecha <=" in sql:
            row = SimpleNamespace(precio_promedio=self.anterior) if self.anterior is not None else None
            return _FakeExec(row)
        if "fecha = :fecha" in sql:
            row = SimpleNamespace(precio_promedio=self.exacto) if self.exacto is not None else None
            return _FakeExec(row)
        return _FakeExec(None)


def test_get_price_for_date_usa_precio_exacto():
    m = XMPriceMapper(FakeDB(exacto=210, anterior=190))
    r = m.get_price_for_date("2026-06-15")
    assert r.precio == Decimal("210") and r.fuente == FUENTE_DIARIO


def test_get_price_for_date_fallback_al_anterior():
    m = XMPriceMapper(FakeDB(exacto=None, anterior=190))
    r = m.get_price_for_date("2026-06-15")
    assert r.precio == Decimal("190") and r.fuente == FUENTE_FALLBACK


def test_get_price_for_date_fallback_a_base():
    m = XMPriceMapper(FakeDB(exacto=None, anterior=None), precio_base=175)
    r = m.get_price_for_date("2026-06-15")
    assert r.precio == Decimal("175") and r.fuente == FUENTE_BASE


def test_get_price_for_date_sin_datos_ni_base():
    m = XMPriceMapper(FakeDB(exacto=None, anterior=None))
    r = m.get_price_for_date("2026-06-15")
    assert r.precio is None and r.fuente == FUENTE_NINGUNA


def test_cache_evita_consultas_redundantes():
    db = FakeDB(exacto=210)
    m = XMPriceMapper(db)
    m.get_price_for_date("2026-06-15")
    llamadas_tras_primera = db.calls
    m.get_price_for_date("2026-06-15")  # misma fecha → desde caché
    assert db.calls == llamadas_tras_primera


def test_get_month_average_usa_promedio_de_bolsa():
    m = XMPriceMapper(FakeDB(mes=Decimal("205.5")))
    r = m.get_month_average(2026, 6)
    assert r.precio == Decimal("205.5") and r.fuente == FUENTE_MES


def test_get_month_average_fallback_a_base():
    m = XMPriceMapper(FakeDB(mes=None), precio_base=160)
    r = m.get_month_average(2026, 6)
    assert r.precio == Decimal("160") and r.fuente == FUENTE_BASE
