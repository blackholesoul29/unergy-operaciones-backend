"""ViewSet de "Registros CND/ASIC".

Seguimiento del proceso de conexion (CREG 174 -> 9.4) anclado a un Proyecto
existente. Acceso: admin + operaciones.

Un solo ViewSet para las 21 rutas porque todas cuelgan del mismo registro: los
equipos, los documentos y los parametros 9.3 no existen fuera de el y no tienen
url propia. Separarlos en tres ViewSets obligaria a repetir la busqueda del
registro padre en cada uno sin ganar nada.
"""

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.exceptions import NoProcesable
from api.logging import class_logger_wrapper
from api.permissions import RolePermission
from apps.proyectos.models import Proyecto
from apps.registros_cnd import models as rc_models
from apps.registros_cnd.services import registros as registros_service
from apps.registros_cnd.services import state_machine as sm
from apps.registros_cnd.services.correos import TIPOS_CORREO, generar_correo
from apps.registros_cnd.services.dominio import (
    ETAPAS_ACTUALES, ETAPAS_FUTURAS, ETIQUETAS_ETAPA, HITOS,
    Responsable, TipoDocumento, TipoEquipoFrontera, TipoVisitaProtecciones,
)
from apps.registros_cnd.services.validaciones_93 import Entradas93, validar_93

from . import serializers as rc_serializers


def _valores(clase) -> list[str]:
    """Los valores de una clase-catalogo de `dominio.py` (no son Enum, son
    constantes de clase)."""
    return [v for k, v in vars(clase).items() if not k.startswith("_")]


@class_logger_wrapper(name="Operaciones | Registros CND")
class RegistroCndViewSet(viewsets.GenericViewSet):
    """Registros de conexion CND/ASIC.

    GET    /api/v1/registros-cnd/catalogos
    GET    /api/v1/registros-cnd/proyectos-disponibles[?q=]
    GET|POST /api/v1/registros-cnd
    POST   /api/v1/registros-cnd/por-proyecto/{proyecto_id}
    GET|PATCH /api/v1/registros-cnd/{registro_id}
    POST   /api/v1/registros-cnd/{registro_id}/transicion
    GET|PUT /api/v1/registros-cnd/{registro_id}/parametros-93
    GET    /api/v1/registros-cnd/{registro_id}/validacion-93
    GET|POST /api/v1/registros-cnd/{registro_id}/equipos
    PATCH|DELETE /api/v1/registros-cnd/{registro_id}/equipos/{equipo_id}
    GET|POST /api/v1/registros-cnd/{registro_id}/documentos
    PATCH|DELETE /api/v1/registros-cnd/{registro_id}/documentos/{documento_id}
    POST   /api/v1/registros-cnd/{registro_id}/alertas/recomputar
    POST   /api/v1/registros-cnd/{registro_id}/correos/{tipo}

    **El listado trae una fila por proyecto, no por registro**: los que aun no
    tienen registro salen en 0% con el hito 1a pendiente, para poder irlos
    llenando desde la misma pantalla.
    """

    permission_classes = [RolePermission]
    required_role = ["operaciones"]
    pagination_class = None                 # el contrato devuelve listas planas
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    queryset = rc_models.RegistroConexion.objects.all()
    # Sin esto `{pk}` tambien casa "catalogos": el router pone las rutas sin
    # detalle primero, pero acotar el id es mas barato que confiar en el orden.
    lookup_value_regex = r"\d+"

    def get_serializer_class(self):
        return {
            "create": rc_serializers.RegistroConexionCreateSerializer,
            "partial_update": rc_serializers.RegistroConexionUpdateSerializer,
        }.get(self.action, rc_serializers.RegistroConexionUpdateSerializer)

    def _registro(self, registro_id) -> rc_models.RegistroConexion:
        reg = registros_service.con_relaciones().filter(pk=registro_id).first()
        if reg is None:
            raise NotFound("Registro no encontrado")
        return reg

    # ── Catalogos ─────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="catalogos")
    def catalogos(self, request):
        """Todo lo que el frontend necesita para renderizar etapas, transiciones
        e hitos sin hardcodear la maquina de estados."""
        etapas_todas = [*ETAPAS_ACTUALES, *ETAPAS_FUTURAS]
        return Response({
            "etapas": [{"value": e, "label": ETIQUETAS_ETAPA[e]} for e in ETAPAS_ACTUALES],
            "etapas_futuras": [{"value": e, "label": ETIQUETAS_ETAPA[e]} for e in ETAPAS_FUTURAS],
            "hitos": [
                {"codigo": h["key"], "etapa": h["etapa"],
                 "peso_default": h["peso_default"], "descripcion": h["descripcion"]}
                for h in HITOS
            ],
            "transiciones": {e: sm.get_etapa_def(e)["transiciones"] for e in etapas_todas},
            "iniciales": {e: sm.get_etapa_def(e)["inicial"] for e in etapas_todas},
            "tipos_documento": _valores(TipoDocumento),
            "tipos_equipo": _valores(TipoEquipoFrontera),
            "tipos_visita": [TipoVisitaProtecciones.VIRTUAL, TipoVisitaProtecciones.PRESENCIAL],
            "responsables": _valores(Responsable),
            "tipos_correo": list(TIPOS_CORREO),
        })

    @action(detail=False, methods=["get"], url_path="proyectos-disponibles")
    def proyectos_disponibles(self, request):
        """Proyectos que aun no tienen registro — alimenta el dialogo "Registrar"."""
        qs = Proyecto.objects.filter(deleted_at__isnull=True)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(nombre_comercial__icontains=q)
        # El limite se aplica ANTES de descartar los que ya tienen registro,
        # igual que en FastAPI: el dialogo es un buscador, no un inventario.
        proyectos = list(qs.order_by("nombre_comercial")[:300])
        con_registro = set(
            rc_models.RegistroConexion.objects
            .filter(proyecto_id__in=[p.id for p in proyectos])
            .values_list("proyecto_id", flat=True)
        )
        return Response(rc_serializers.ProyectoDisponibleSerializer(
            [p for p in proyectos if p.id not in con_registro], many=True,
        ).data)

    # ── CRUD de registros ─────────────────────────────────────────────────

    def list(self, request, *args, **kwargs):
        return Response(registros_service.listar_todos())

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reg = registros_service.crear_registro(**serializer.validated_data)
        except ValueError as exc:
            raise NoProcesable(str(exc))
        return Response(
            registros_service.construir_resumen(self._registro(reg.id)),
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path=r"por-proyecto/(?P<proyecto_id>\d+)")
    def por_proyecto(self, request, proyecto_id=None):
        """Materializa (crea si no existe) el registro del proyecto y devuelve su
        resumen. Lo usa el detalle al abrir un proyecto."""
        try:
            reg = registros_service.get_or_create_registro(int(proyecto_id))
        except ValueError as exc:
            raise NotFound(str(exc))
        return Response(registros_service.construir_resumen(self._registro(reg.id)))

    def retrieve(self, request, pk=None):
        return Response(registros_service.construir_resumen(self._registro(pk)))

    def partial_update(self, request, pk=None):
        reg = self._registro(pk)
        serializer = self.get_serializer(reg, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(registros_service.construir_resumen(self._registro(pk)))

    @action(detail=True, methods=["post"], url_path="transicion")
    def transicion(self, request, pk=None):
        reg = self._registro(pk)
        entrada = rc_serializers.TransicionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        try:
            registros_service.registrar_transicion(
                reg, datos["etapa"], datos["a_estado"],
                nota=datos.get("nota"), actor=datos.get("actor"),
            )
        except sm.TransicionInvalidaError as exc:
            raise NoProcesable(str(exc))
        except ValueError as exc:
            raise ValidationError(str(exc))
        return Response(registros_service.construir_resumen(self._registro(pk)))

    # ── Parametros 9.3 + validacion ───────────────────────────────────────

    @action(detail=True, methods=["get", "put"], url_path="parametros-93")
    def parametros_93(self, request, pk=None):
        reg = self._registro(pk)
        params = reg.parametros_93.first()
        if request.method == "GET":
            if params is None:
                return Response(None)
            return Response(rc_serializers.Parametros93Serializer(params).data)

        serializer = rc_serializers.Parametros93Serializer(
            params, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(registro=reg)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="validacion-93")
    def validacion_93(self, request, pk=None):
        p = self._registro(pk).parametros_93.first()
        if p is None:
            return Response({"valido": True, "resultados": [], "sin_parametros": True})
        return Response(validar_93(Entradas93(
            icc_subtrans_pico_kap=p.icc_subtrans_pico_kap,
            icc_subtrans_3f_ka=p.icc_subtrans_3f_ka,
            icc_subtrans_2f_ka=p.icc_subtrans_2f_ka,
            icc_subtrans_1f_ka=p.icc_subtrans_1f_ka,
            icc_estado_estable_ka=p.icc_estado_estable_ka,
            voltaje_max_kv=p.voltaje_max_kv,
            voltaje_nominal_kv=p.voltaje_nominal_kv,
            voltaje_min_kv=p.voltaje_min_kv,
            in_eq_ka=p.in_eq_ka,
        )))

    # ── Equipos de frontera ───────────────────────────────────────────────

    @action(detail=True, methods=["get", "post"], url_path="equipos")
    def equipos(self, request, pk=None):
        reg = self._registro(pk)
        if request.method == "GET":
            return Response(rc_serializers.EquipoSerializer(reg.equipos.all(), many=True).data)
        serializer = rc_serializers.EquipoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(registro=reg)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch", "delete"], url_path=r"equipos/(?P<equipo_id>\d+)")
    def equipo(self, request, pk=None, equipo_id=None):
        eq = rc_models.RegistroEquipoFrontera.objects.filter(
            pk=equipo_id, registro_id=pk,
        ).first()
        if eq is None:
            raise NotFound("Equipo no encontrado")
        if request.method == "DELETE":
            eq.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = rc_serializers.EquipoSerializer(eq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # ── Documentos ────────────────────────────────────────────────────────

    @action(detail=True, methods=["get", "post"], url_path="documentos")
    def documentos(self, request, pk=None):
        reg = self._registro(pk)
        if request.method == "GET":
            return Response(rc_serializers.DocumentoSerializer(reg.documentos.all(), many=True).data)
        serializer = rc_serializers.DocumentoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(registro=reg)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch", "delete"], url_path=r"documentos/(?P<documento_id>\d+)")
    def documento(self, request, pk=None, documento_id=None):
        doc = rc_models.RegistroDocumento.objects.filter(
            pk=documento_id, registro_id=pk,
        ).first()
        if doc is None:
            raise NotFound("Documento no encontrado")
        if request.method == "DELETE":
            doc.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = rc_serializers.DocumentoSerializer(doc, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # ── Alertas ───────────────────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="alertas/recomputar")
    def recomputar_alertas(self, request, pk=None):
        reg = self._registro(pk)
        creadas = registros_service.recomputar_alertas(reg)
        return Response({
            "creadas": len(creadas),
            "alertas": [
                {"tipo": a.tipo, "mensaje": a.mensaje, "estado": a.estado,
                 "fecha_disparo": a.fecha_disparo}
                for a in reg.alertas.all()
            ],
        })

    # ── Correos tipo (borradores) ─────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path=r"correos/(?P<tipo>[\w-]+)")
    def correos(self, request, pk=None, tipo=None):
        try:
            return Response(generar_correo(self._registro(pk), tipo))
        except ValueError as exc:
            raise ValidationError(str(exc))
