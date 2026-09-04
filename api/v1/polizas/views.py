"""ViewSet de la vista de pólizas."""

from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.response import Response

from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.contratos import models as ct_models
from apps.contratos.services import polizas as polizas_service
from apps.proyectos import models as py_models

from . import queryset as polizas_queryset
from . import serializers as polizas_serializers


@class_logger_wrapper(name="Operaciones | Contratos | Pólizas")
class PolizaViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """Pólizas por proyecto.

    GET /api/v1/polizas[?search=&tipo_proyecto=&poliza_om=]
        Una fila por proyecto vivo, con su póliza al lado si la tiene.
    PUT /api/v1/polizas/{proyecto_id}
        Crea o actualiza la póliza del proyecto. `valor_total_proyecto` y
        `valor_lucro_cesante` se recalculan siempre y se ignoran si vienen.

    El identificador de la ruta es el id del PROYECTO, no el de la póliza: la
    póliza puede no existir todavía y el PUT es un upsert.
    """

    permission_classes = [RolePermission]
    pagination_class = None                 # el listado no está paginado hoy
    http_method_names = ["get", "put", "head", "options"]
    serializer_class = polizas_serializers.PolizaFilaSerializer
    queryset = py_models.Proyecto.objects.none()

    def list(self, request, *args, **kwargs):
        poliza_om = request.query_params.get("poliza_om")
        if poliza_om is not None:
            poliza_om = poliza_om.lower() in ("true", "1", "si", "sí")

        proyectos = polizas_queryset.proyectos_con_poliza(
            search=request.query_params.get("search"),
            tipo_proyecto=request.query_params.get("tipo_proyecto"),
            poliza_om=poliza_om,
        )
        filas = polizas_queryset.build_filas(proyectos)
        return Response(polizas_serializers.PolizaFilaSerializer(filas, many=True).data)

    def update(self, request, *args, **kwargs):
        """Upsert de la póliza del proyecto."""
        proyecto = get_object_or_404(
            py_models.Proyecto, pk=kwargs["pk"], deleted_at__isnull=True
        )
        poliza = ct_models.Poliza.objects.filter(proyecto=proyecto).first()

        serializer = polizas_serializers.PolizaUpsertSerializer(
            poliza, data=request.data
        )
        serializer.is_valid(raise_exception=True)
        poliza = serializer.save(proyecto=proyecto)

        # Los derivados se recalculan SIEMPRE al guardar, con los valores ya
        # persistidos, para que no puedan quedar desincronizados de sus insumos.
        poliza.valor_total_proyecto, poliza.valor_lucro_cesante = (
            polizas_service.calcular_derivados(
                poliza.mano_obra, poliza.estructura, poliza.paneles,
                poliza.inversores, poliza.otros, poliza.ipp_base,
                poliza.ipp_provisional, poliza.tarifa_base,
                poliza.generacion_anual_p90_kwh,
            )
        )
        poliza.save(update_fields=["valor_total_proyecto", "valor_lucro_cesante"])

        fila = polizas_queryset.build_filas(
            polizas_queryset.proyectos_con_poliza().filter(pk=proyecto.pk)
        )[0]
        return Response(polizas_serializers.PolizaFilaSerializer(fila).data)
