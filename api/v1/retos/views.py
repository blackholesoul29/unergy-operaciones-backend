"""ViewSets del tablero de retos.

Dos recursos: el trimestre (`/retos`) y la metrica (`/retos/metricas`). Se
separan porque la metrica se edita por su propio id, sin pasar por el trimestre.
"""

from datetime import date

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.retos import models as rt_models

from . import queryset as retos_queryset
from . import serializers as retos_serializers


@class_logger_wrapper(name="Operaciones | Retos | Trimestres")
class RetoViewSet(
    viewsets.GenericViewSet, mixins.RetrieveModelMixin, mixins.UpdateModelMixin
):
    """Tablero trimestral de retos del equipo.

    GET    /api/v1/retos[?anio=YYYY]        listado del año, con los 4 Q
    GET    /api/v1/retos/{id}               detalle con semanas y matriz de valores
    PATCH  /api/v1/retos/{id}               nombre, descripción y rango de fechas
    POST   /api/v1/retos/{id}/metricas      crea una métrica en el trimestre
    POST   /api/v1/retos/{id}/metricas/copiar-desde/{origen_id}

    El rango del Q es editable y no puede pasar de 60 semanas. Mover el rango no
    borra valores: los que quedan fuera dejan de mostrarse.
    """

    permission_classes = [RolePermission]
    pagination_class = None                 # el listado devuelve su propia envoltura
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = rt_models.RetoTrimestre.objects.all()

    def get_queryset(self):
        return retos_queryset.con_metricas_y_valores()

    def get_serializer_class(self):
        if self.action == "partial_update":
            return retos_serializers.RetoUpdateSerializer
        return retos_serializers.RetoDetalleSerializer

    def list(self, request, *args, **kwargs):
        """Los 4 trimestres del año pedido, autocreándolos si faltan.

        No es un listado paginado: el contrato es
        `{anio, anios_disponibles, retos}` y el frontend lo consume asi.
        """
        anio_param = request.query_params.get("anio")
        if anio_param is not None and not anio_param.lstrip("-").isdigit():
            # Sin esto un valor no numerico llega al ORM y sale como 500.
            raise ValidationError({"anio": "Debe ser un año entero."})
        anio = int(anio_param) if anio_param else date.today().year

        retos_queryset.asegurar_trimestres(anio)
        retos = [
            retos_queryset.build_reto(r)[0]
            for r in self.get_queryset().filter(anio=anio).order_by("trimestre")
        ]
        datos = {
            "anio": anio,
            "anios_disponibles": retos_queryset.anios_disponibles(anio),
            "retos": retos,
        }
        return Response(retos_serializers.RetosAnioSerializer(datos).data)

    def retrieve(self, request, *args, **kwargs):
        reto = retos_queryset.build_detalle(self.get_object())
        return Response(retos_serializers.RetoDetalleSerializer(reto).data)

    def partial_update(self, request, *args, **kwargs):
        reto = self.get_object()
        serializer = retos_serializers.RetoUpdateSerializer(
            reto, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        reto = retos_queryset.build_detalle(self.get_queryset().get(pk=reto.pk))
        return Response(retos_serializers.RetoDetalleSerializer(reto).data)

    @action(detail=True, methods=["post"], url_path="metricas")
    @log_endpoint(name="Operaciones | Retos | Crear métrica")
    def crear_metrica(self, request, pk=None):
        reto = get_object_or_404(rt_models.RetoTrimestre, pk=pk)
        serializer = retos_serializers.MetricaCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        orden = serializer.validated_data.pop("orden", None)
        if orden is None:
            # Al final de la lista: el maximo actual + 1, o 0 si es la primera.
            maximo = (
                rt_models.RetoMetrica.objects.filter(reto=reto)
                .order_by("-orden").values_list("orden", flat=True).first()
            )
            orden = (maximo + 1) if maximo is not None else 0

        metrica = serializer.save(reto=reto, orden=orden, activa=True)
        metrica = retos_queryset.metrica_recalculada(metrica)
        return Response(
            retos_serializers.MetricaResumenSerializer(metrica).data, status=201
        )

    @action(
        detail=True, methods=["post"],
        url_path=r"metricas/copiar-desde/(?P<origen_id>[^/.]+)",
    )
    @log_endpoint(name="Operaciones | Retos | Copiar métricas")
    def copiar_metricas(self, request, pk=None, origen_id=None):
        """Copia las métricas activas de otro trimestre, sin duplicar por nombre."""
        if str(origen_id) == str(pk):
            raise ValidationError("El reto de origen debe ser distinto al de destino")
        destino = get_object_or_404(rt_models.RetoTrimestre, pk=pk)
        origen = get_object_or_404(rt_models.RetoTrimestre, pk=origen_id)

        existentes = {
            (n or "").strip().lower()
            for n in rt_models.RetoMetrica.objects.filter(reto=destino)
            .values_list("nombre", flat=True)
        }
        creadas = []
        with transaction.atomic():
            for m in rt_models.RetoMetrica.objects.filter(reto=origen, activa=True):
                clave = (m.nombre or "").strip().lower()
                if clave in existentes:
                    continue
                existentes.add(clave)
                creadas.append(rt_models.RetoMetrica.objects.create(
                    reto=destino, nombre=m.nombre, descripcion=m.descripcion,
                    unidad=m.unidad, meta=m.meta, tipo_agregacion=m.tipo_agregacion,
                    direccion=m.direccion, decimales=m.decimales,
                    responsable=m.responsable, orden=m.orden, activa=True,
                ))

        anotadas = [retos_queryset.metrica_recalculada(m) for m in creadas]
        return Response(
            retos_serializers.MetricaResumenSerializer(anotadas, many=True).data
        )


@class_logger_wrapper(name="Operaciones | Retos | Métricas")
class MetricaViewSet(
    viewsets.GenericViewSet, mixins.DestroyModelMixin
):
    """Métricas de un trimestre, editables por su propio id.

    PATCH  /api/v1/retos/metricas/{id}
    DELETE /api/v1/retos/metricas/{id}                      → 204
    PUT    /api/v1/retos/metricas/{id}/valores/{semana}     semana = lunes ISO
    """

    permission_classes = [RolePermission]
    http_method_names = ["put", "patch", "delete", "head", "options"]
    serializer_class = retos_serializers.MetricaUpdateSerializer
    queryset = rt_models.RetoMetrica.objects.select_related("reto").prefetch_related(
        "valores"
    )

    def partial_update(self, request, *args, **kwargs):
        metrica = self.get_object()
        serializer = self.get_serializer(metrica, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # Un null explicito sobre una columna NOT NULL se ignora, no revienta:
        # el front manda el objeto completo con los campos que no toca en null.
        no_nulos = ("nombre", "tipo_agregacion", "direccion", "decimales", "orden", "activa")
        datos = {
            k: v for k, v in serializer.validated_data.items()
            if not (v is None and k in no_nulos)
        }
        for campo, valor in datos.items():
            setattr(metrica, campo, valor)
        metrica.save()
        return Response(
            retos_serializers.MetricaResumenSerializer(
                retos_queryset.metrica_recalculada(metrica)
            ).data
        )

    @action(
        detail=True, methods=["put"],
        url_path=r"valores/(?P<semana_inicio>\d{4}-\d{2}-\d{2})",
    )
    @log_endpoint(name="Operaciones | Retos | Guardar valor semanal")
    def guardar_valor(self, request, pk=None, semana_inicio=None):
        from apps.retos.services import calculo as svc

        metrica = self.get_object()
        semana = date.fromisoformat(semana_inicio)
        if semana.weekday() != 0:
            raise ValidationError("La semana debe empezar en lunes")

        reto = metrica.reto
        semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, date.today())
        if semana not in {s["inicio"] for s in semanas}:
            raise ValidationError("La semana está fuera del rango del trimestre")

        serializer = retos_serializers.ValorSemanalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rt_models.RetoValorSemanal.objects.update_or_create(
            metrica=metrica, semana_inicio=semana,
            defaults={
                **serializer.validated_data,
                "actualizado_por_id": getattr(request.user, "id", None),
            },
        )
        metrica.refresh_from_db()
        return Response(
            retos_serializers.MetricaResumenSerializer(
                retos_queryset.metrica_recalculada(metrica)
            ).data
        )
