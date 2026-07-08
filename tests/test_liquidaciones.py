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


# ── Resumen espejo del Panel Contable (función pura) ────────────────────────────

def _mk_linea(pi_id, nombre, pct, grupo, concepto, valor, orden):
    return SimpleNamespace(proyecto_inversionista_id=pi_id, inversionista_nombre=nombre,
                           porcentaje=pct, grupo=grupo, concepto=concepto,
                           valor_cop=valor, orden=orden)


def _mk_panel(pid, lineas):
    return SimpleNamespace(id=pid * 10, proyecto_id=pid, lineas=lineas,
                           consecutivo_ingresos=5, consecutivo_costos=None,
                           fecha_firma=None, liquidar_ingresos=True, liquidar_costos=False)


def test_resumen_panel_usa_grupo_resultado():
    from app.api.v1.liquidaciones import _construir_resumen_panel
    panel = _mk_panel(11, [
        _mk_linea(71, "INV A", 100.0, "ingresos", "Ingreso", 1000.0, 0),
        _mk_linea(71, "INV A", 100.0, "resultado", "Resultado", 800.0, 1),
    ])
    out = _construir_resumen_panel(
        [panel], "2026-05", "preliquidacion",
        {11: "Proyecto X"}, {11: "minigranja"},
        {11: 500}, {71: {"cliente_id": 9, "cliente_nombre": "Cli A"}},
    )
    p = out["proyectos"][0]
    assert p["tipo_proyecto"] == "minigranja"
    assert p["liquidacion_id"] == 500
    inv = p["inversionistas"][0]
    assert inv["valor_a_pagar"] == 800.0            # usa 'resultado', no la fórmula
    assert inv["cliente_id"] == 9 and inv["cliente_nombre"] == "Cli A"


def test_resumen_panel_fallback_sin_resultado():
    from app.api.v1.liquidaciones import _construir_resumen_panel
    panel = _mk_panel(12, [
        _mk_linea(80, "INV B", 100.0, "ingresos", "Ingreso", 1000.0, 0),
        _mk_linea(80, "INV B", 100.0, "comercializacion", "Comer", 50.0, 1),
        _mk_linea(80, "INV B", 100.0, "costos", "Costo", 200.0, 2),
    ])
    out = _construir_resumen_panel(
        [panel], "2026-05", "preliquidacion",
        {12: "Proyecto Y"}, {12: None}, {}, {},
    )
    p = out["proyectos"][0]
    inv = p["inversionistas"][0]
    assert inv["valor_a_pagar"] == 750.0            # 1000 - 50 - 200
    assert inv["cliente_nombre"] == "INV B"         # sin cliente en el mapa → nombre de línea
    assert p["liquidacion_id"] is None
    assert out["resumen"]["num_proyectos"] == 1


def test_route_literales_antes_de_id():
    """Rutas literales de 1 segmento deben registrarse ANTES de /{id}, o Starlette
    las intercepta (bug histórico 422 en /resumen). Guarda contra regresión."""
    from app.api.v1.liquidaciones import router
    paths = [r.path for r in router.routes]
    i_id = paths.index("/liquidaciones/{id}")
    for literal in ("/liquidaciones/resumen-panel", "/liquidaciones/resumen"):
        assert paths.index(literal) < i_id, f"{literal} debe ir antes de /{{id}}"
