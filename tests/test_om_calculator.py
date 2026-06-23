"""Tests del calculador O&M: override manual del valor a facturar."""
from datetime import date
from app.services.om_calculator import calcular_proyecto

# tasas: clave = año diciembre DANE; enero N+1 usa ipc_tasas[N]
IPC = {2024: 0.052, 2025: 0.051}


def _fila(**kw):
    base = dict(
        contrato_id=1,
        nombre_proyecto="Demo",
        fecha_inicio=date(2024, 1, 1),
        valor_base_anual=48_000_000,
        periodo="2026-06",
        ipc_tasas=IPC,
    )
    base.update(kw)
    return calcular_proyecto(**base)


def test_sin_override_valor_calculado_es_valor_a_facturar():
    f = _fila()
    assert f["editado_manual"] is False
    assert f["valor_calculado"] == f["valor_a_facturar"]
    assert f["valor_calculado"] is not None


def test_con_override_gana_y_conserva_calculado():
    f = _fila(valor_manual=5_000_000)
    assert f["editado_manual"] is True
    assert f["valor_a_facturar"] == 5_000_000
    assert f["valor_calculado"] != 5_000_000
    assert f["valor_calculado"] is not None


def test_override_none_equivale_a_sin_override():
    assert _fila(valor_manual=None) == _fila()


def test_fila_deshabilitada_ignora_override():
    f = _fila(valor_base_anual=None, valor_manual=9_999_999)
    assert f["habilitado"] is False
    assert f["editado_manual"] is False
    assert f["valor_a_facturar"] is None
    assert f["valor_calculado"] is None
