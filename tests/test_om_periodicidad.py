"""Rediseño Task 3: ciclos de periodicidad — corresponde_cobro_este_mes y el
flag aplica_este_mes en calcular_proyecto."""
from datetime import date

from app.services.om_calculator import corresponde_cobro_este_mes, calcular_proyecto

FB = date(2026, 1, 15)   # fecha base: enero 2026


def test_mensual_siempre_desde_el_inicio():
    assert corresponde_cobro_este_mes("mensual", FB, "2026-01") is True
    assert corresponde_cobro_este_mes("mensual", FB, "2026-05") is True


def test_antes_del_inicio_no_aplica():
    assert corresponde_cobro_este_mes("mensual", FB, "2025-12") is False


def test_trimestral():
    casos = {"2026-01": True, "2026-02": False, "2026-04": True, "2026-07": True, "2026-06": False}
    for p, exp in casos.items():
        assert corresponde_cobro_este_mes("trimestral", FB, p) is exp


def test_semestral():
    assert corresponde_cobro_este_mes("semestral", FB, "2026-01") is True
    assert corresponde_cobro_este_mes("semestral", FB, "2026-07") is True
    assert corresponde_cobro_este_mes("semestral", FB, "2026-04") is False


def test_anual():
    assert corresponde_cobro_este_mes("anual", FB, "2026-01") is True
    assert corresponde_cobro_este_mes("anual", FB, "2027-01") is True
    assert corresponde_cobro_este_mes("anual", FB, "2026-06") is False


def _calc(periodo, periodicidad):
    return calcular_proyecto(
        contrato_id=1, nombre_proyecto="D", fecha_firma_contrato=date(2026, 1, 1),
        fecha_inicio_om=None, valor_base_anual=12_000_000, periodo=periodo,
        ipc_tasas={}, periodicidad=periodicidad,
    )


def test_calcular_proyecto_incluye_aplica_este_mes():
    assert _calc("2026-04", "trimestral")["aplica_este_mes"] is True
    assert _calc("2026-02", "trimestral")["aplica_este_mes"] is False
