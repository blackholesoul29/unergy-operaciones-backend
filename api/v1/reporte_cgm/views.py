"""ViewSet del reporte CGM: un solo endpoint, `POST /reporte-cgm/enviar`."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.energia.services import cgm_envio
from apps.fronteras import models as fr_models

from . import serializers as cgm_serializers


@class_logger_wrapper(name="Operaciones | Energía | Reporte CGM")
class ReporteCGMViewSet(viewsets.GenericViewSet):
    """Manda el reporte CGM (extracción de Quoia + Excel ASIC) por correo.

    A quién le llega qué se resuelve SIEMPRE en la base: del cuerpo solo se
    cree el par (tipo, id) del destinatario y su filtro opcional de proyectos.

    Nunca falla entero: cada destinatario reporta su propio `ok`/`error`, así
    que un correo mal configurado no tumba el envío de los demás.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    queryset = fr_models.Frontera.objects.none()

    @log_endpoint(name="Operaciones | Reporte CGM | Enviar")
    @action(detail=False, methods=["post"], url_path="enviar")
    def enviar(self, request):
        ser = cgm_serializers.EnviarSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response(cgm_envio.enviar(**ser.validated_data))
