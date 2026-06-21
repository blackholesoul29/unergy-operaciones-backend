"""Tests de la lógica pura de propagación Cliente → PPA (sync_client_ppa).

Solo se prueba el diffing/decisión (funciones puras), sin tocar la BD, igual
que el resto de tests del repo (SimpleNamespace en vez de ORM).
"""
from types import SimpleNamespace

from app.services.sync_client_ppa import (
    FieldChange,
    apply_changes,
    diff_cliente_ppa,
)


def _cliente(**kw):
    base = dict(id=1, razon_social_nombre="Terpel S.A.", nit_cedula="900123456")
    base.update(kw)
    return SimpleNamespace(**base)


def _ppa(**kw):
    base = dict(
        id=10,
        nombre_interno="PPA-001",
        numero_codigo_contrato="C-001",
        comprador_id=None,
        vendedor_id=None,
        comprador_nombre=None,
        comprador_nit=None,
        vendedor_nombre=None,
        vendedor_nit=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_nit_change_on_comprador_is_critical():
    cliente = _cliente(nit_cedula="900999999")
    ppa = _ppa(comprador_id=1, comprador_nombre="Terpel S.A.", comprador_nit="900123456")
    changes = diff_cliente_ppa(cliente, ppa)
    assert len(changes) == 1
    ch = changes[0]
    assert ch.field_changed == "comprador_nit"
    assert ch.old_value == "900123456"
    assert ch.new_value == "900999999"
    assert ch.is_critical is True


def test_nombre_change_is_not_critical():
    cliente = _cliente(razon_social_nombre="Terpel Colombia S.A.")
    ppa = _ppa(comprador_id=1, comprador_nombre="Terpel S.A.", comprador_nit="900123456")
    changes = diff_cliente_ppa(cliente, ppa)
    assert len(changes) == 1
    assert changes[0].field_changed == "comprador_nombre"
    assert changes[0].is_critical is False


def test_no_changes_when_values_match():
    cliente = _cliente()
    ppa = _ppa(comprador_id=1, comprador_nombre="Terpel S.A.", comprador_nit="900123456")
    assert diff_cliente_ppa(cliente, ppa) == []


def test_whitespace_and_none_are_normalized():
    cliente = _cliente(razon_social_nombre="  Terpel S.A. ", nit_cedula="900123456")
    ppa = _ppa(comprador_id=1, comprador_nombre="Terpel S.A.", comprador_nit="900123456")
    assert diff_cliente_ppa(cliente, ppa) == []


def test_cliente_not_linked_yields_no_changes():
    cliente = _cliente(id=99)
    ppa = _ppa(comprador_id=1, comprador_nombre="Otro", comprador_nit="111")
    assert diff_cliente_ppa(cliente, ppa) == []


def test_vendedor_role_detected():
    cliente = _cliente(id=5, nit_cedula="800555")
    ppa = _ppa(vendedor_id=5, vendedor_nombre="Terpel S.A.", vendedor_nit="800000")
    changes = diff_cliente_ppa(cliente, ppa)
    assert [c.field_changed for c in changes] == ["vendedor_nit"]
    assert changes[0].is_critical is True


def test_both_nombre_and_nit_change():
    cliente = _cliente(razon_social_nombre="Nuevo", nit_cedula="999")
    ppa = _ppa(comprador_id=1, comprador_nombre="Viejo", comprador_nit="111")
    changes = diff_cliente_ppa(cliente, ppa)
    fields = sorted(c.field_changed for c in changes)
    assert fields == ["comprador_nit", "comprador_nombre"]
    assert sum(c.is_critical for c in changes) == 1


def test_same_cliente_as_comprador_and_vendedor():
    cliente = _cliente(id=7, razon_social_nombre="AutoVenta", nit_cedula="700")
    ppa = _ppa(
        comprador_id=7, vendedor_id=7,
        comprador_nombre="AutoVenta", comprador_nit="700",
        vendedor_nombre="AutoVenta", vendedor_nit="699",
    )
    changes = diff_cliente_ppa(cliente, ppa)
    assert [c.field_changed for c in changes] == ["vendedor_nit"]


def test_apply_changes_mutates_ppa_and_reports():
    ppa = _ppa(comprador_id=1, comprador_nombre="Viejo", comprador_nit="111")
    changes = [
        FieldChange("comprador_nombre", "Viejo", "Nuevo", False),
        FieldChange("comprador_nit", "111", "999", True),
    ]
    assert apply_changes(ppa, changes) is True
    assert ppa.comprador_nombre == "Nuevo"
    assert ppa.comprador_nit == "999"


def test_apply_changes_empty_is_noop():
    ppa = _ppa(comprador_nombre="Viejo")
    assert apply_changes(ppa, []) is False
    assert ppa.comprador_nombre == "Viejo"
