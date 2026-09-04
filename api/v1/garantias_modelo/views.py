"""ViewSet del Modelo Predictivo de Garantias — solo transporte.

El contrato lo congelo el plan 1 y el frontend ya esta en produccion
consumiendolo: no cambiar nombres de campo sin cambiar la vista.
"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.exceptions import NoProcesable
from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.garantias.models import GarCalculo
from apps.garantias.services import modelo_predictivo


def _rango(request, nombre, defecto, minimo, maximo, tipo):
    """Los `Query(..., ge=, le=)` de FastAPI: fuera de rango es 422, no 400."""
    crudo = request.query_params.get(nombre)
    if crudo is None:
        return defecto
    try:
        valor = tipo(crudo)
    except (TypeError, ValueError):
        raise NoProcesable(f"{nombre} debe ser {tipo.__name__}")
    if not (minimo <= valor <= maximo):
        raise NoProcesable(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


@class_logger_wrapper(name="Operaciones | Garantías | Modelo")
class GarantiaModeloViewSet(viewsets.GenericViewSet):
    """Modelo Predictivo de Garantías.

    GET /api/v1/garantias/modelo/plan[?agente=&esquema=&cuantil=&horizonte=]
    GET /api/v1/garantias/modelo/detalle/{id}

    `id` es `vencimiento|periodo_ini` — lo arma el propio plan, no se compone
    en el frontend.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "head", "options"]
    queryset = GarCalculo.objects.none()

    @action(detail=False, methods=["get"], url_path="plan")
    def plan(self, request):
        """Lo que hay que reservar para los próximos vencimientos.

        `horizonte` se ignora cuando `esquema` es mensual — el frontend lo envía
        siempre.
        """
        return Response(modelo_predictivo.construir_plan(
            agente=request.query_params.get("agente") or "UNGG",
            esquema=request.query_params.get("esquema") or "semanal",
            cuantil=_rango(request, "cuantil", 0.9, 0.5, 0.99, float),
            horizonte=_rango(request, "horizonte", 4, 1, 12, int),
        ))

    @action(detail=False, methods=["get"], url_path=r"detalle/(?P<id>[^/]+)")
    def detalle(self, request, id=None):
        """Cadena de cálculo, descomposición del ancho e insumos de un vencimiento."""
        return Response(modelo_predictivo.construir_detalle(id=id))
