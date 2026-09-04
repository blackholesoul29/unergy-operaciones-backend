"""ViewSet del historial de ajustes de garantías XM."""

from rest_framework import mixins, viewsets
from rest_framework.response import Response

from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.garantias import models as ga_models

from . import serializers as ajustes_serializers


@class_logger_wrapper(name="Operaciones | Garantías | Ajustes XM")
class GarantiaAjusteViewSet(
    viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin,
    mixins.UpdateModelMixin, mixins.DestroyModelMixin,
):
    """Ajustes de garantías: semanal, TXR y mensual.

    GET    /api/v1/garantias-ajustes        más reciente primero
    POST   /api/v1/garantias-ajustes        → 201
    PATCH  /api/v1/garantias-ajustes/{id}
    DELETE /api/v1/garantias-ajustes/{id}   → 204
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    queryset = ga_models.GarantiaAjuste.objects.order_by("-fecha", "-id")

    def get_serializer_class(self):
        if self.action == "create":
            return ajustes_serializers.GarantiaAjusteEscrituraSerializer
        if self.action == "partial_update":
            return ajustes_serializers.GarantiaAjusteUpdateSerializer
        return ajustes_serializers.GarantiaAjusteSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ajuste = serializer.save()
        return Response(
            ajustes_serializers.GarantiaAjusteSerializer(ajuste).data, status=201
        )

    def partial_update(self, request, *args, **kwargs):
        ajuste = self.get_object()
        serializer = self.get_serializer(ajuste, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            ajustes_serializers.GarantiaAjusteSerializer(ajuste).data
        )
