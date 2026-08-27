"""Los endpoints del Modelo Predictivo respetan el contrato que el frontend consume.

El frontend ya está en producción llamando estas rutas: si el prefijo o los nombres
cambian, la tab se rompe sin que ninguna prueba del backend se entere. De ahí que se
fije la forma del router, no solo que importe.
"""
from app.api.v1 import garantias_modelo
from app.api.v1.garantias_modelo import router
from app.api.v1.router import api_router


def test_el_router_expone_las_dos_rutas():
    rutas = {r.path for r in router.routes}
    assert "/garantias/modelo/plan" in rutas
    assert "/garantias/modelo/detalle/{id}" in rutas


def test_el_prefijo_es_el_del_contrato():
    assert router.prefix == "/garantias/modelo"


def test_las_rutas_son_get():
    for r in router.routes:
        assert "GET" in r.methods


def test_el_router_esta_registrado_en_la_api():
    """Registrar el módulo y olvidar el include_router deja los endpoints en 404."""
    rutas = {r.path for r in api_router.routes}
    assert "/api/v1/garantias/modelo/plan" in rutas
    assert "/api/v1/garantias/modelo/detalle/{id}" in rutas


def test_el_endpoint_del_plan_acepta_horizonte_con_esquema_mensual():
    """El frontend manda `horizonte` en todas las llamadas, también en mensual donde
    no aplica. Tiene que ser un parámetro válido, no un error 422."""
    firma = garantias_modelo.get_plan.__annotations__
    assert "horizonte" in firma
    assert "esquema" in firma
