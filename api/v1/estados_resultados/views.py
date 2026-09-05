"""ViewSet de Estados de Resultados: listado y descarga desde Drive."""

from urllib.parse import quote

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.contabilidad import models as cb_models
from apps.contabilidad.services import drive

from . import queryset as er_queryset
from . import serializers as er_serializers

LIMITE_DEFECTO = 300
LIMITE_MAXIMO = 1000
# Tope de la descarga masiva. Los archivos pesan ~9 KB, así que 600 son ~6 MB:
# el límite es por el tiempo de bajarlos de Drive uno a uno, no por el peso.
ZIP_MAX_ARCHIVOS = 600
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _content_disposition(nombre: str) -> str:
    """Cabecera segura: los nombres de estos archivos traen tildes y comas."""
    respaldo_ascii = nombre.encode("ascii", "ignore").decode() or "descarga.xlsx"
    return (
        f'attachment; filename="{respaldo_ascii}"; '
        f"filename*=UTF-8''{quote(nombre)}"
    )


@class_logger_wrapper(name="Operaciones | Contabilidad | Estados de resultados")
class EstadoResultadoViewSet(viewsets.GenericViewSet):
    """Los ER que viven en la carpeta de Drive. Solo lectura.

    GET /api/v1/estados-resultados/archivos[?mes=&anio=&tipo=&version=&q=&limite=&refrescar=]
    GET /api/v1/estados-resultados/archivos/{file_id}/descargar
    GET /api/v1/estados-resultados/archivos-zip[?mismos filtros]

    La carpeta tiene ~1 700 archivos y se filtra en el servidor. La generación de
    los ER no pasa por acá; esto solo los expone para que nadie necesite permisos
    sobre la carpeta (los tiene el service account).
    """

    permission_classes = [RolePermission]
    queryset = cb_models.PanelContable.objects.none()

    @action(detail=False, methods=["get"], url_path="archivos")
    def archivos(self, request):
        limite = request.query_params.get("limite", str(LIMITE_DEFECTO))
        if not limite.isdigit() or not 1 <= int(limite) <= LIMITE_MAXIMO:
            raise ValidationError(
                {"limite": f"Entre 1 y {LIMITE_MAXIMO}."}
            )
        refrescar = request.query_params.get("refrescar", "").lower() in ("true", "1")

        datos = er_queryset.build_listado(
            er_queryset.cargar(refrescar),
            er_queryset.leer_filtros(request.query_params),
            int(limite),
        )
        return Response(er_serializers.ArchivosERSerializer(datos).data)

    @action(
        detail=False, methods=["get"],
        url_path=r"archivos/(?P<file_id>[^/.]+)/descargar",
    )
    @log_endpoint(name="Operaciones | Contabilidad | ER | Descargar")
    def descargar(self, request, file_id=None):
        """Descarga un archivo, proxeado por el service account.

        Se comprueba que el id esté EN la carpeta de ER: el service account
        también lee otros shared drives (soportes del Panel, adjuntos de
        fallas), y sin esta validación el endpoint sería un proxy abierto a todo
        lo que él ve.
        """
        archivo = next(
            (a for a in er_queryset.cargar() if a["id"] == file_id), None
        )
        if archivo is None:
            raise NotFound(
                "El archivo no está en la carpeta de estados de resultados"
            )
        try:
            contenido = drive.descargar_archivo(file_id)
        except drive.DriveNoConfigurado:
            raise er_queryset.DriveNoConfigurado("Google Drive no configurado")
        except drive.DriveSinAcceso:
            raise er_queryset.DriveSinAcceso("Sin acceso al archivo en Drive")

        respuesta = HttpResponse(contenido, content_type=MIME_XLSX)
        respuesta["Content-Disposition"] = _content_disposition(
            archivo.get("name") or "archivo.xlsx"
        )
        return respuesta

    @action(detail=False, methods=["get"], url_path="archivos-zip")
    @log_endpoint(name="Operaciones | Contabilidad | ER | ZIP")
    def archivos_zip(self, request):
        """Todos los archivos que pasan los filtros, en un ZIP.

        Usa el mismo `filtrar_archivos` que el listado, así que el ZIP trae
        exactamente lo que el usuario ve en la tabla.
        """
        filtros = er_queryset.leer_filtros(request.query_params)
        seleccion = drive.filtrar_archivos(er_queryset.cargar(), **filtros)
        if not seleccion:
            raise NotFound("No hay archivos que coincidan con los filtros")
        if len(seleccion) > ZIP_MAX_ARCHIVOS:
            return Response(
                {"detail": (
                    f"Son {len(seleccion)} archivos y el máximo por ZIP es "
                    f"{ZIP_MAX_ARCHIVOS}. Filtra por período o versión."
                )},
                status=413,
            )
        try:
            contenido = drive.construir_zip(seleccion)
        except drive.DriveNoConfigurado:
            raise er_queryset.DriveNoConfigurado("Google Drive no configurado")

        respuesta = HttpResponse(contenido, content_type="application/zip")
        respuesta["Content-Disposition"] = _content_disposition(
            self._nombre_del_zip(filtros) + ".zip"
        )
        return respuesta

    @staticmethod
    def _nombre_del_zip(filtros: dict) -> str:
        tipo = filtros.get("tipo")
        if tipo == drive.TIPO_ER:
            partes = ["estados_resultados"]
        elif tipo == drive.TIPO_CRUCE:
            partes = ["cruce_facturas"]
        else:
            partes = ["archivos"]
        if filtros.get("anio") and filtros.get("mes"):
            partes.append(f'{filtros["anio"]}-{filtros["mes"]:02d}')
        if filtros.get("version"):
            partes.append(filtros["version"].lower())
        return "_".join(partes)
