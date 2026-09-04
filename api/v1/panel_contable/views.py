"""ViewSet del Panel Contable.

Las respuestas salen tal cual de `apps.contabilidad.services.panel`: son dicts
que ya tienen la forma que sirve FastAPI hoy, y volver a pasarlos por un
serializer los reescribiría. Los serializers de este paquete son solo de
entrada.
"""

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.contabilidad import models as cb_models
from apps.contabilidad.services import panel as svc

from . import serializers as pc_serializers

ROLES_ESCRITURA = ["admin", "liquidaciones"]
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _validado(serializer_class, request):
    ser = serializer_class(data=request.data)
    ser.is_valid(raise_exception=True)
    return ser.validated_data


@class_logger_wrapper(name="Operaciones | Contabilidad | Panel Contable")
class PanelContableViewSet(viewsets.GenericViewSet):
    """Preliquidaciones y liquidaciones oficiales a partir de los ER por proyecto.

    - `cargar-er`: recalcula con LibreOffice, parsea, matchea el proyecto, divide
      por % del backend y guarda un panel + líneas (borrador editable).
    - `cargar-periodo`: lo mismo pero desde la API, sin archivo.
    - listado: los paneles del período con sus líneas por inversionista.
    - `PATCH /{id}`: flags y consecutivos del panel, o edición de una línea.
    - `diferencia`: cruza preliquidación vs oficial.

    **Escribir exige rol `admin` o `liquidaciones`**; leer, solo estar autenticado.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    queryset = cb_models.PanelContable.objects.none()

    # `soporte` no está: subir y quitar un soporte es del rol de operación, igual
    # que en FastAPI (solo pedía sesión, no `_require_write`).
    ESCRITURAS = (
        "cargar_er", "cargar_periodo", "guardar_clasificacion", "redividir",
        "partial_update", "mapeo_celda", "alias_fuente", "fuente_ingreso",
        "reasignar_consecutivos",
    )

    def get_permissions(self):
        # `clasificacion` sirve GET y POST en la misma acción: el rol se exige por
        # método, no por acción, o el GET quedaría cerrado de más.
        escribe = self.action in self.ESCRITURAS or (
            self.action == "clasificacion" and self.request.method == "POST"
        )
        if escribe:
            self.required_role = ROLES_ESCRITURA
        return super().get_permissions()

    # ── Carga ────────────────────────────────────────────────────────────────
    @log_endpoint(name="Operaciones | Panel Contable | Cargar ER")
    @action(detail=False, methods=["post"], url_path="cargar-er")
    def cargar_er(self, request):
        return Response(svc.cargar_er(
            archivos=request.FILES.getlist("files"),
            periodo=request.data.get("periodo"),
            tipo=request.data.get("tipo") or "preliquidacion",
            tipo_carga=request.data.get("tipo_carga") or "normal",
            usuario_id=getattr(request.user, "id", None),
        ))

    @log_endpoint(name="Operaciones | Panel Contable | Cargar período")
    @action(detail=False, methods=["post"], url_path="cargar-periodo")
    def cargar_periodo(self, request):
        datos = _validado(pc_serializers.CargarPeriodoSerializer, request)
        return Response(svc.cargar_periodo(
            periodo_pedido=datos["periodo"], tipo=datos["tipo"],
            version=datos["version"], usuario_id=getattr(request.user, "id", None),
        ))

    @action(detail=False, methods=["get"], url_path="contraste")
    def contraste(self, request):
        return Response(svc.contraste_api_vs_excel(
            periodo=request.query_params.get("periodo"),
            tipo=request.query_params.get("tipo") or "oficial",
            version=request.query_params.get("version") or "txf",
        ))

    # ── Clasificación NEU/Nitro ──────────────────────────────────────────────
    @action(detail=False, methods=["get", "post"], url_path="clasificacion")
    def clasificacion(self, request):
        if request.method == "GET":
            return Response(svc.listar_clasificacion(
                request.query_params.get("periodo")))
        datos = _validado(pc_serializers.ClasificacionSerializer, request)
        return Response(svc.guardar_clasificacion(
            datos["periodo"], datos["asignaciones"]))

    # ── Listado y detalle ────────────────────────────────────────────────────
    def list(self, request):
        return Response(svc.listar(
            periodo=request.query_params.get("periodo"),
            tipo=request.query_params.get("tipo") or "preliquidacion",
        ))

    def partial_update(self, request, pk=None):
        datos = _validado(pc_serializers.PanelPatchSerializer, request)
        return Response(svc.actualizar(int(pk), datos))

    @action(detail=True, methods=["get"], url_path="estado-resultados")
    def estado_resultados(self, request, pk=None):
        contenido, nombre = svc.estado_resultados_xlsx(
            int(pk), request.query_params.get("inversionista") or None)
        respuesta = HttpResponse(contenido, content_type=MIME_XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        return respuesta

    # ── Soportes en Drive ────────────────────────────────────────────────────
    @action(detail=True, methods=["post", "delete"], url_path="soporte")
    def soporte(self, request, pk=None):
        if request.method == "DELETE":
            return Response(svc.eliminar_soporte(
                int(pk), request.query_params.get("grupo"),
                request.query_params.get("concepto"),
            ))
        return Response(svc.subir_soporte(
            int(pk), request.data.get("grupo"), request.data.get("concepto"),
            request.FILES.get("archivo"), request.user,
        ))

    # ── Re-división ──────────────────────────────────────────────────────────
    @log_endpoint(name="Operaciones | Panel Contable | Redividir")
    @action(detail=False, methods=["post"], url_path="redividir")
    def redividir(self, request):
        datos = _validado(pc_serializers.RedividirSerializer, request)
        return Response(svc.redividir(
            periodo=datos["periodo"], tipo=datos["tipo"],
            proyecto_id=datos["proyecto_id"], forzar=datos["forzar"],
        ))

    # ── Mapeo de celda y fuentes de ingreso ──────────────────────────────────
    @action(detail=False, methods=["post"], url_path="mapeo-celda")
    def mapeo_celda(self, request):
        datos = _validado(pc_serializers.MapeoCeldaSerializer, request)
        return Response(svc.guardar_mapeo_celda(**datos))

    @action(detail=False, methods=["post"], url_path="alias-fuente")
    def alias_fuente(self, request):
        datos = _validado(pc_serializers.AliasFuenteSerializer, request)
        return Response(svc.guardar_alias_fuente(**datos))

    @action(detail=False, methods=["post", "delete"], url_path="fuente-ingreso")
    def fuente_ingreso(self, request):
        if request.method == "DELETE":
            datos = _validado(pc_serializers.QuitarFuenteIngresoSerializer, request)
            return Response(svc.quitar_fuente_ingreso(**datos))
        datos = _validado(pc_serializers.FuenteIngresoSerializer, request)
        return Response(svc.agregar_fuente_ingreso(**datos))

    # ── Consecutivos ─────────────────────────────────────────────────────────
    @log_endpoint(name="Operaciones | Panel Contable | Reasignar consecutivos")
    @action(detail=False, methods=["post"], url_path="reasignar-consecutivos")
    def reasignar_consecutivos(self, request):
        datos = _validado(pc_serializers.ReasignarConsecutivosSerializer, request)
        return Response(svc.reasignar_consecutivos(**datos))

    @action(detail=False, methods=["get"], url_path="consecutivos-usados")
    def consecutivos_usados(self, request):
        crudo = request.query_params.get("excluir_panel_id")
        return Response(svc.consecutivos_usados(int(crudo) if crudo else None))

    # ── Diferencia ───────────────────────────────────────────────────────────
    @action(detail=False, methods=["get"], url_path="diferencia")
    def diferencia(self, request):
        return Response(svc.diferencia(request.query_params.get("periodo")))
