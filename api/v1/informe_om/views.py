"""ViewSet del Informe de Puesta en Marcha."""

from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.comun import drive_evidencia
from apps.om import models as om_models
from apps.om.services import evidencia as evidencia_service
from apps.om.services import forma_ficha
from apps.proyectos import models as py_models

from . import queryset as informe_queryset
from . import serializers as informe_serializers


@class_logger_wrapper(name="Operaciones | O&M | Informe de puesta en marcha")
class InformeOmViewSet(viewsets.GenericViewSet):
    """Ficha de puesta en marcha por proyecto.

    GET    /api/v1/informe-om/proyectos                         listado con estado
    GET    /api/v1/informe-om/{proyecto_id}                     detalle completo
    PUT    /api/v1/informe-om/{proyecto_id}                     guarda la ficha
    POST   /api/v1/informe-om/{proyecto_id}/archivos/{seccion}  sube evidencia
    DELETE /api/v1/informe-om/{proyecto_id}/archivos/{seccion}/{archivo_id}

    **El identificador es el del PROYECTO, no el de la ficha**: la ficha puede
    no existir todavía y el PUT la crea. Los cuatro semáforos del checklist se
    calculan, no se guardan: ver `apps/om/services/checklist.py`.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "put", "post", "delete", "head", "options"]
    queryset = py_models.Proyecto.objects.none()

    @action(detail=False, methods=["get"], url_path="proyectos")
    def proyectos(self, request):
        return Response(informe_serializers.ListItemSerializer(
            informe_queryset.build_listado(), many=True
        ).data)

    def retrieve(self, request, *args, **kwargs):
        proyecto = self._proyecto(kwargs["pk"])
        ficha = om_models.ProyectoInformeOm.objects.filter(
            proyecto=proyecto
        ).first()
        return self._detalle(proyecto, ficha)

    def update(self, request, *args, **kwargs):
        """Guarda la ficha completa. Crea la fila si es la primera vez."""
        proyecto = self._proyecto(kwargs["pk"])
        ficha = om_models.ProyectoInformeOm.objects.filter(
            proyecto=proyecto
        ).first()

        serializer = informe_serializers.FichaSerializer(
            ficha, data=request.data
        )
        serializer.is_valid(raise_exception=True)
        # Los checklist se guardan con su forma completa aunque el cliente mande
        # solo lo que cambió: la lectura da por hecho que todas las claves están.
        datos = forma_ficha.normalizar(serializer.validated_data)

        if ficha is None:
            ficha = om_models.ProyectoInformeOm(proyecto=proyecto)
        for campo, valor in datos.items():
            setattr(ficha, campo, valor)
        ficha.save()
        return self._detalle(proyecto, ficha)

    @action(
        detail=True, methods=["post"],
        url_path=r"archivos/(?P<seccion>[\w-]+)",
    )
    @log_endpoint(name="Operaciones | O&M | Informe | Subir evidencia")
    def subir_evidencia(self, request, pk=None, seccion=None):
        destino = self._seccion(seccion)
        proyecto = self._proyecto(pk)
        ficha = self._ficha_o_crear(proyecto)

        archivo = request.FILES.get("archivo")
        if archivo is None:
            raise ValidationError({"archivo": "Falta el archivo."})

        try:
            adjunto = drive_evidencia.subir(
                archivo, [proyecto.nombre_comercial, destino.etiqueta]
            )
        except drive_evidencia.ArchivoDemasiadoGrande as exc:
            raise ValidationError(str(exc))
        except drive_evidencia.DriveNoConfigurado as exc:
            return Response({"detail": str(exc)}, status=500)
        except drive_evidencia.DriveFallo as exc:
            return Response({"detail": str(exc)}, status=500)

        destino.escribir(ficha, [*destino.leer(ficha), adjunto])
        ficha.save()
        return Response(adjunto)

    @action(
        detail=True, methods=["delete"],
        url_path=r"archivos/(?P<seccion>[\w-]+)/(?P<archivo_id>[^/]+)",
    )
    @log_endpoint(name="Operaciones | O&M | Informe | Eliminar evidencia")
    def eliminar_evidencia(self, request, pk=None, seccion=None, archivo_id=None):
        destino = self._seccion(seccion)
        ficha = self._ficha_o_crear(self._proyecto(pk))

        actuales = destino.leer(ficha)
        restantes = [a for a in actuales if a.get("id") != archivo_id]
        if len(restantes) == len(actuales):
            raise NotFound("Archivo no encontrado")

        drive_evidencia.eliminar(archivo_id)
        destino.escribir(ficha, restantes)
        ficha.save()
        return Response({"status": "ok"})

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _proyecto(pk):
        return get_object_or_404(
            py_models.Proyecto, pk=pk, deleted_at__isnull=True
        )

    @staticmethod
    def _seccion(nombre):
        destino = evidencia_service.SECCIONES.get(nombre)
        if destino is None:
            raise NotFound("Sección de evidencia no reconocida")
        return destino

    @staticmethod
    def _ficha_o_crear(proyecto):
        ficha, _ = om_models.ProyectoInformeOm.objects.get_or_create(
            proyecto=proyecto
        )
        return ficha

    @staticmethod
    def _detalle(proyecto, ficha):
        return Response(informe_serializers.DetalleSerializer(
            informe_queryset.build_detalle(proyecto, ficha)
        ).data)
