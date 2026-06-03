"""Tests de los serializers puros de liquidaciones (robustez None)."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from app.api.v1.liquidaciones import _serializar_costo, _serializar_linea


def test_costo_full():
    c = SimpleNamespace(id=1, tipo_costo="op", descripcion="x", proveedor="P",
                        nro_soporte="N1", soporte_url=None, valor_cop=Decimal("100.5"),
                        created_at=datetime(2026, 6, 1, 9, 0, 0))
    out = _serializar_costo(c)
    assert out["valor_cop"] == 100.5 and out["created_at"] == "2026-06-01T09:00:00"


def test_costo_none_valor_and_date_do_not_crash():
    c = SimpleNamespace(id=2, tipo_costo=None, descripcion=None, proveedor=None,
                        nro_soporte=None, soporte_url=None, valor_cop=None, created_at=None)
    out = _serializar_costo(c)
    assert out["valor_cop"] is None and out["created_at"] is None


def test_linea_none_valor_does_not_crash():
    l = SimpleNamespace(id=3, tipo_linea=None, concepto="c", valor_cop=None,
                        porcentaje=None, base_calculo_cop=None, referencia_factura=None, orden=1)
    out = _serializar_linea(l)
    assert out["valor_cop"] is None and out["orden"] == 1
