"""ViewSet de Monitoreo Solar nacional (datos XM SinergoX)."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.energia.services import xm_solar
from apps.proyectos import models as py_models

from . import queryset as solar_queryset

TOP_DEFECTO = 15
TOP_MAXIMO = 100

# Los nombres de los query params son camelCase porque así los manda el
# frontend hoy; se conservan tal cual.
FILTROS = {
    "fecha_ini": "fechaIni", "fecha_fin": "fechaFin",
    "municipios": "municipio", "departamentos": "departamento",
    "estados": "estado",
}


@class_logger_wrapper(name="Operaciones | Energía | Solar nacional")
class SolarViewSet(viewsets.GenericViewSet):
    """Proyectos solares del país y su generación, desde los Excel de XM.

    GET  /api/v1/solar/proyectos
    GET  /api/v1/solar/filtros            valores únicos para los selectores
    GET  /api/v1/solar/generacion[?fechaIni=&fechaFin=&municipio=&departamento=&estado=]
    GET  /api/v1/solar/ranking[?…&top=15]
    GET  /api/v1/solar/comparacion[?…&sicNacionales=&idsInternos=]
    POST /api/v1/solar/reload-cache

    Todo sale de dos Excel en `datos/`, con caché en memoria de 5 minutos. Si
    los archivos no existen, los endpoints devuelven listas vacías en vez de
    fallar: es un módulo de consulta y un archivo que falta no es un error del
    cliente.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "post", "head", "options"]
    queryset = py_models.Proyecto.objects.none()

    def _filtros(self, request) -> dict:
        return {
            interno: request.query_params.get(externo)
            for interno, externo in FILTROS.items()
        }

    @action(detail=False, methods=["get"], url_path="proyectos")
    def proyectos(self, request):
        return Response(xm_solar.datos()["proyectos"])

    @action(detail=False, methods=["get"], url_path="filtros")
    def filtros(self, request):
        proyectos = xm_solar.datos()["proyectos"]
        return Response({
            "municipios": sorted(
                {p["municipio"] for p in proyectos if p["municipio"]}
            ),
            "departamentos": sorted(
                {p["departamento"] for p in proyectos if p["departamento"]}
            ),
            "estados": sorted({p["estado"] for p in proyectos if p["estado"]}),
        })

    @action(detail=False, methods=["get"], url_path="generacion")
    def generacion(self, request):
        return Response(xm_solar.filtrar_generacion(
            xm_solar.datos()["generacion"], **self._filtros(request)
        ))

    @action(detail=False, methods=["get"], url_path="ranking")
    def ranking(self, request):
        crudo = request.query_params.get("top", str(TOP_DEFECTO))
        if not crudo.isdigit() or not 1 <= int(crudo) <= TOP_MAXIMO:
            raise ValidationError({"top": f"Entero entre 1 y {TOP_MAXIMO}."})
        filas = xm_solar.filtrar_generacion(
            xm_solar.datos()["generacion"], **self._filtros(request)
        )
        return Response(solar_queryset.build_ranking(filas, int(crudo)))

    @action(detail=False, methods=["get"], url_path="comparacion")
    def comparacion(self, request):
        return Response(solar_queryset.build_comparacion(
            request.query_params.get("sicNacionales"),
            request.query_params.get("idsInternos"),
            request.query_params.get("fechaIni"),
            request.query_params.get("fechaFin"),
        ))

    @action(detail=False, methods=["post"], url_path="reload-cache")
    @log_endpoint(name="Operaciones | Energía | Solar | Recargar caché")
    def reload_cache(self, request):
        xm_solar.invalidar_cache()
        datos = xm_solar.datos()
        return Response({
            "ok": True,
            "proyectos": len(datos["proyectos"]),
            "registros_generacion": len(datos["generacion"]),
            "archivos": {
                "listado_recursos": xm_solar.RECURSOS_FILE.exists(),
                "generacion_distribuida": xm_solar.GENERACION_FILE.exists(),
            },
        })
