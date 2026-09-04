"""ViewSet de verificación de costos."""

from django.db.models import F
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.proyectos import models as py_models

from . import serializers as vc_serializers


@class_logger_wrapper(name="Operaciones | Proyectos | Verificación de costos")
class VerificacionCostoViewSet(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin,
    mixins.UpdateModelMixin, mixins.DestroyModelMixin,
):
    """Costos declarados por proyecto, uno por proyecto.

    GET    /api/v1/verificacion-costos      ordenado por nombre del proyecto
    POST   /api/v1/verificacion-costos      409 si el proyecto ya tiene una
    PATCH  /api/v1/verificacion-costos/{id}
    DELETE /api/v1/verificacion-costos/{id} → 204
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        # El nombre del proyecto se anota en la consulta: leerlo desde el
        # serializer por fila sería un N+1.
        return (
            py_models.VerificacionCosto.objects.select_related("proyecto")
            .annotate(proyecto_nombre=F("proyecto__nombre_comercial"))
            .order_by("proyecto__nombre_comercial")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return vc_serializers.VerificacionCostoCreateSerializer
        if self.action == "partial_update":
            return vc_serializers.VerificacionCostoUpdateSerializer
        return vc_serializers.VerificacionCostoSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verificacion = serializer.save()
        return Response(self._leer(verificacion.pk), status=201)

    def partial_update(self, request, *args, **kwargs):
        verificacion = self.get_object()
        serializer = self.get_serializer(verificacion, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._leer(verificacion.pk))

    def _leer(self, pk) -> dict:
        """Relee con la anotación del nombre, que el serializer de salida usa."""
        return vc_serializers.VerificacionCostoSerializer(
            self.get_queryset().get(pk=pk)
        ).data
