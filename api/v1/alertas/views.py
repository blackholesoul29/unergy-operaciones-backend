"""ViewSet de alertas operativas."""

from datetime import date

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.monitoreo import models as mo_models

from . import queryset as alertas_queryset
from . import serializers as alertas_serializers

UMBRAL_DEFECTO = 90.0


@class_logger_wrapper(name="Operaciones | Monitoreo | Alertas")
class AlertaViewSet(viewsets.GenericViewSet):
    """Alertas operativas del estado GESCON/ASIC y de cumplimiento PPA.

    GET   /api/v1/alertas/ppa-vencimiento[?status=]
    PATCH /api/v1/alertas/ppa-vencimiento/{id}
    GET   /api/v1/alertas/contratos-ppa            huérfanos y duplicados
    GET   /api/v1/alertas/cumplimiento-ppa[?anio=&mes=&umbral_pct=]

    Solo `ppa-vencimiento` sale de una tabla; los otros dos se calculan en cada
    petición y no persisten nada.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]
    serializer_class = alertas_serializers.AlertaSerializer
    queryset = mo_models.Alerta.objects.none()

    @action(detail=False, methods=["get"], url_path="ppa-vencimiento")
    def ppa_vencimiento(self, request):
        alertas = alertas_queryset.alertas_persistidas(
            request.query_params.get("status")
        )
        return Response(self.get_serializer(alertas, many=True).data)

    @action(
        detail=False, methods=["patch"],
        url_path=r"ppa-vencimiento/(?P<alerta_id>[^/.]+)",
    )
    @log_endpoint(name="Operaciones | Monitoreo | Alertas | Estado")
    def actualizar_estado(self, request, alerta_id=None):
        alerta = mo_models.Alerta.objects.filter(pk=alerta_id).first()
        if alerta is None:
            raise NotFound("Alerta no encontrada")
        entrada = alertas_serializers.ActualizarEstadoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        alerta.status = entrada.validated_data["status"]
        alerta.save(update_fields=["status"])
        return Response(self.get_serializer(alerta).data)

    @action(detail=False, methods=["get"], url_path="contratos-ppa")
    def contratos_ppa(self, request):
        return Response(alertas_queryset.build_contratos_ppa())

    @action(detail=False, methods=["get"], url_path="cumplimiento-ppa")
    def cumplimiento_ppa(self, request):
        hoy = date.today()
        anio = self._entero(request, "anio", 2020, 2050, hoy.year)
        mes = self._entero(request, "mes", 1, 12, hoy.month)
        umbral = self._decimal(request, "umbral_pct", 0, 100, UMBRAL_DEFECTO)
        return Response(
            alertas_queryset.build_cumplimiento_ppa(anio, mes, umbral)
        )

    @staticmethod
    def _entero(request, nombre, minimo, maximo, defecto) -> int:
        crudo = request.query_params.get(nombre)
        if crudo in (None, ""):
            return defecto
        if not crudo.isdigit() or not minimo <= int(crudo) <= maximo:
            raise ValidationError({nombre: f"Entero entre {minimo} y {maximo}."})
        return int(crudo)

    @staticmethod
    def _decimal(request, nombre, minimo, maximo, defecto) -> float:
        crudo = request.query_params.get(nombre)
        if crudo in (None, ""):
            return defecto
        try:
            valor = float(crudo)
        except ValueError:
            raise ValidationError({nombre: "Debe ser un número."})
        if not minimo <= valor <= maximo:
            raise ValidationError({nombre: f"Entre {minimo} y {maximo}."})
        return valor
