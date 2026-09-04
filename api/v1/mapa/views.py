"""ViewSet del mapa OR."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from api.logging import class_logger_wrapper
from apps.proyectos import models as py_models
from apps.proyectos.services import mapa_externo


@class_logger_wrapper(name="Operaciones | Mapa OR")
class MapaViewSet(viewsets.GenericViewSet):
    """Datos geográficos para el mapa de fallas.

    GET /api/v1/mapa/operadores          operadores de red disponibles
    GET /api/v1/mapa?operator=<code>     circuitos, subestaciones y minigranjas

    **Sin autenticación, igual que hoy.** El router de FastAPI no declara
    `get_current_user` en ninguno de los dos endpoints; añadirla acá rompería a
    quien los consuma. Es una diferencia con el resto de la API que conviene
    revisar, pero no de tapadillo dentro de una migración de framework.
    """

    permission_classes = [AllowAny]
    queryset = py_models.Proyecto.objects.none()

    def list(self, request, *args, **kwargs):
        operador = request.query_params.get("operator", "")
        if not 1 <= len(operador) <= 50:
            raise ValidationError({"operator": "Requerido, entre 1 y 50 caracteres."})
        if not mapa_externo.OPERADOR_VALIDO.match(operador):
            raise ValidationError("Operador inválido")
        return Response(mapa_externo.mapa(operador))

    @action(detail=False, methods=["get"], url_path="operadores")
    def operadores(self, request):
        return Response(mapa_externo.operadores())
