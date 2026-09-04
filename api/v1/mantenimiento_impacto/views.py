"""ViewSet del impacto de mantenimiento."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.monitoreo import models as mo_models
from apps.monitoreo.services import impacto as impacto_service

from . import serializers as mi_serializers


@class_logger_wrapper(name="Operaciones | Monitoreo | Impacto de mantenimiento")
class MantenimientoImpactoViewSet(viewsets.GenericViewSet):
    """Impacto de los eventos de mantenimiento.

    GET    /api/v1/mantenimiento-impacto[?proyecto_id=&maintenance_type=
           &fecha_inicio=&fecha_fin=]
    POST   /api/v1/mantenimiento-impacto      → 201
    GET|PUT|DELETE /api/v1/mantenimiento-impacto/{id}

    **Energía perdida, impacto económico y bandera PPA no se editan**: se
    recalculan en cada escritura para que reflejen siempre la ventana y la
    generación del evento. Sí se pueden fijar a mano la generación esperada y la
    real; lo que se omita sale del histórico de `generacion_diaria`.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "post", "put", "delete", "head", "options"]
    queryset = mo_models.MantenimientoImpacto.objects.all()

    def _impacto(self, pk):
        fila = mo_models.MantenimientoImpacto.objects.filter(
            pk=pk
        ).select_related("proyecto").first()
        if fila is None:
            raise NotFound("Registro de impacto no encontrado")
        return fila

    def list(self, request, *args, **kwargs):
        consulta = mo_models.MantenimientoImpacto.objects.select_related(
            "proyecto"
        )
        for parametro, filtro in (
            ("proyecto_id", "proyecto_id"),
            ("maintenance_type", "maintenance_type"),
            ("fecha_inicio", "start_time__gte"),
            ("fecha_fin", "start_time__lte"),
        ):
            valor = request.query_params.get(parametro)
            if valor:
                consulta = consulta.filter(**{filtro: valor})
        return Response(mi_serializers.ImpactoSerializer(
            consulta.order_by("-start_time"), many=True
        ).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(
            mi_serializers.ImpactoSerializer(self._impacto(kwargs["pk"])).data
        )

    def create(self, request, *args, **kwargs):
        entrada = mi_serializers.ImpactoEscrituraSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        impacto = mo_models.MantenimientoImpacto(
            **entrada.validated_data, created_by=request.user.id
        )
        impacto_service.aplicar(impacto)
        impacto.save()
        return Response(
            mi_serializers.ImpactoSerializer(self._impacto(impacto.pk)).data,
            status=201,
        )

    def update(self, request, *args, **kwargs):
        impacto = self._impacto(kwargs["pk"])
        entrada = mi_serializers.ImpactoEscrituraSerializer(
            impacto, data=request.data, partial=True
        )
        entrada.is_valid(raise_exception=True)
        for campo, valor in entrada.validated_data.items():
            setattr(impacto, campo, valor)
        impacto_service.aplicar(impacto)
        impacto.save()
        return Response(
            mi_serializers.ImpactoSerializer(self._impacto(impacto.pk)).data
        )

    def destroy(self, request, *args, **kwargs):
        self._impacto(kwargs["pk"]).delete()
        return Response(status=204)
