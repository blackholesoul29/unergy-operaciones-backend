"""Todo `response_model` declarado en la app tiene que poder construirse.

Bug real (2026-09-03): `GET /contratos-servicio` devolvía 500 con cualquier
parámetro, y también el detalle -- el recurso entero caído desde el
2026-08-30 22:31. La causa:

    facturas_solenium: Optional[List[FilaFactura]] = None

`FilaFactura` se había renombrado a `ContratoFacturaCreate` (64fbfc3, cuando
los JSONB facturas_solenium/inversionistas se reemplazaron por la tabla
contrato_factura), pero quedaron dos campos apuntando al nombre viejo. Como
las anotaciones son diferidas, el import NO falla: falla Pydantic al construir
el modelo, y eso pasa recién al serializar la respuesta. Resultado: un 500 por
petición, sin error al arrancar y sin que ningún test lo notara.

Los tests de endpoints no lo agarraron porque no había ninguno sobre
/contratos-servicio. Este test no necesita uno por endpoint: recorre las rutas
registradas y verifica que el `response_model` de cada una sea construible, que
es la precondición que FastAPI necesita para poder responder.
"""
from app.main import app


def test_todos_los_response_model_se_pueden_construir():
    """`app.openapi()` recorre cada ruta registrada y resuelve su
    `response_model` para poder describirlo. Una forward ref sin definir
    revienta acá, igual que reventaría al serializar una respuesta real.

    Se pasa por openapi() y no por app.routes porque esta version de FastAPI
    difiere la inclusion de los routers en un `_IncludedRouter`: recorrer
    app.routes a mano encuentra 7 rutas en vez de las ~390 reales.
    """
    spec = app.openapi()

    paths = spec.get("paths", {})
    assert len(paths) > 300, (
        f"solo se describieron {len(paths)} rutas -- ¿se dejaron de registrar los routers? "
        "Con pocas rutas este test pasaría sin revisar casi nada."
    )
    # Centinela: si /contratos-servicio deja de estar acá, este test dejó de
    # cubrir justamente el endpoint que motivó escribirlo.
    assert "/api/v1/contratos-servicio" in paths
