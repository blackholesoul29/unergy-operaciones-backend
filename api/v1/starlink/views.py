"""ViewSet de facturas Starlink.

Recurso poco convencional a propósito: la clave no es un id sino el PERÍODO
(`YYYY-MM`), y tres de los ocho endpoints no leen ni escriben la base — parsean
un PDF o generan un Excel. Se respeta la forma que ya tiene el frontend en vez de
"arreglarla" hacia REST, porque el contrato es lo que no puede cambiar.
"""

import io
import json
import re

from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.monitoreo import models as mo_models
from apps.monitoreo.services import starlink as starlink_service
from apps.monitoreo.services.starlink_excel import construir_excel
from apps.monitoreo.services.starlink_parser import parsear_pdf

from . import queryset as starlink_queryset

TAMANO_MAXIMO_PDF = 20 * 1024 * 1024
PERIODO = re.compile(r"^\d{4}-\d{2}$")

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@class_logger_wrapper(name="Operaciones | Monitoreo | Starlink")
class StarlinkViewSet(viewsets.GenericViewSet):
    """Procesamiento de facturas Starlink.

    POST   /api/v1/starlink/procesar-pdf     parsea un PDF, no persiste nada
    POST   /api/v1/starlink/excel            genera el .xlsx y lo descarga
    GET    /api/v1/starlink/periodos         períodos con datos guardados, desc
    GET    /api/v1/starlink/factura/{periodo}
    PUT    /api/v1/starlink/factura/{periodo}   crea o sobreescribe el período
    DELETE /api/v1/starlink/factura/{periodo}
    GET    /api/v1/starlink/mapeo            catálogo sitio→proyecto
    PUT    /api/v1/starlink/mapeo            upsert por `patron`; reprocesa TODO

    El período es `YYYY-MM`.
    """

    permission_classes = [RolePermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = mo_models.StarlinkFactura.objects.none()

    # ── sin persistencia ──────────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="procesar-pdf")
    @log_endpoint(name="Operaciones | Monitoreo | Starlink | Procesar PDF")
    def procesar_pdf(self, request):
        archivo = request.FILES.get("file")
        if archivo is None:
            raise ValidationError({"file": "Falta el archivo."})
        if not archivo.name.lower().endswith(".pdf"):
            raise ValidationError("El archivo debe ser un PDF.")
        if archivo.size > TAMANO_MAXIMO_PDF:
            # 413 y no 400: el cliente puede reintentar con un archivo menor.
            return Response(
                {"detail": "Archivo demasiado grande (máx. 20 MB)."}, status=413
            )

        try:
            resultado = parsear_pdf(archivo.read())
        except Exception as exc:
            return Response({"detail": f"Error al parsear el PDF: {exc}"}, status=422)

        if not resultado["items"]:
            return Response(
                {"detail": "No se encontraron ítems en el PDF. Verifica que sea "
                           "una factura Starlink válida."},
                status=422,
            )
        return Response(resultado)

    @action(detail=False, methods=["post"], url_path="excel")
    @log_endpoint(name="Operaciones | Monitoreo | Starlink | Excel")
    def excel(self, request):
        items = request.data.get("items", [])
        if not items:
            raise ValidationError("Sin datos para generar Excel.")

        libro = construir_excel(items, request.data.get("agrupado", []))
        buffer = io.BytesIO()
        libro.save(buffer)

        respuesta = HttpResponse(buffer.getvalue(), content_type=TIPO_XLSX)
        respuesta["Content-Disposition"] = (
            "attachment; filename=starlink_factura.xlsx"
        )
        return respuesta

    # ── períodos y facturas ───────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="periodos")
    def periodos(self, request):
        return Response(
            list(
                mo_models.StarlinkFactura.objects.order_by("-periodo")
                .values_list("periodo", flat=True)
            )
        )

    @action(
        detail=False, methods=["get", "put", "delete"],
        url_path=r"factura/(?P<periodo>[^/.]+)",
    )
    @log_endpoint(name="Operaciones | Monitoreo | Starlink | Factura")
    def factura(self, request, periodo=None):
        if request.method == "GET":
            return Response(starlink_queryset.build_factura(self._buscar(periodo)))
        if request.method == "DELETE":
            self._buscar(periodo).delete()
            return Response({"ok": True})
        return self._guardar(request, periodo)

    def _buscar(self, periodo):
        factura = mo_models.StarlinkFactura.objects.filter(periodo=periodo).first()
        if factura is None:
            raise NotFound(f"No hay datos para el período {periodo}.")
        return factura

    def _guardar(self, request, periodo):
        if not PERIODO.match(periodo or ""):
            raise ValidationError("Período debe tener formato YYYY-MM.")
        items = request.data.get("items", [])
        if not items:
            raise ValidationError("Sin ítems para guardar.")

        factura, _ = mo_models.StarlinkFactura.objects.update_or_create(
            periodo=periodo,
            defaults={
                "items_json": json.dumps(items, ensure_ascii=False),
                "agrupado_json": json.dumps(
                    request.data.get("agrupado", []), ensure_ascii=False
                ),
                "cargos_totales": request.data.get("cargos_totales"),
                "suma_items": request.data.get("suma_items", 0),
            },
        )
        starlink_service.regenerar_lineas(factura)
        return Response({"ok": True, "periodo": factura.periodo})

    # ── catálogo de mapeos ────────────────────────────────────────────────

    @action(detail=False, methods=["get", "put"], url_path="mapeo")
    @log_endpoint(name="Operaciones | Monitoreo | Starlink | Mapeo")
    def mapeo(self, request):
        if request.method == "GET":
            return Response(starlink_queryset.build_mapeo())

        patron = (request.data.get("patron") or "").strip()
        if not patron:
            raise ValidationError({"patron": "patron es obligatorio."})

        # `excluido` marca el sitio como "no es proyecto nuestro" (p. ej. un tema
        # contable): se guarda sin proyecto y deja de bloquear el export de Costos.
        excluido = bool(request.data.get("excluido", False))
        mapeo, _ = mo_models.StarlinkMapeoSitio.objects.update_or_create(
            patron=patron,
            defaults={
                "proyecto_id": None if excluido else request.data.get("proyecto_id"),
                "activo": request.data.get("activo", True),
                "excluido": excluido,
            },
        )
        # Un patrón nuevo o desactivado cambia a qué proyecto se imputa cada
        # línea de CUALQUIER período ya guardado, así que se reprocesa todo.
        starlink_service.regenerar_todas_las_facturas()
        return Response({"ok": True, "id": mapeo.id, "patron": mapeo.patron})
