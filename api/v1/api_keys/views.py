"""ViewSet de claves de API. Todo el CRUD es solo para administradores."""

from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.plataforma import models as pl_models
from apps.plataforma.services import api_keys as api_keys_service

from . import serializers as api_keys_serializers


@class_logger_wrapper(name="Operaciones | Plataforma | API keys")
class ApiKeyViewSet(viewsets.GenericViewSet, mixins.DestroyModelMixin):
    """Claves de API por usuario.

    POST   /api/v1/api-keys                      → 201, incluye la clave en claro
    GET    /api/v1/api-keys/user/{usuario_id}
    PATCH  /api/v1/api-keys/{id}/toggle          activa/desactiva
    DELETE /api/v1/api-keys/{id}                 → 204
    GET    /api/v1/api-keys/verify               datos del usuario del token

    Todo exige rol `admin` menos `verify`, que solo requiere estar autenticado:
    es el endpoint con el que un cliente comprueba que su credencial sirve.
    """

    permission_classes = [RolePermission]
    required_role = ["admin"]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    serializer_class = api_keys_serializers.ApiKeySerializer
    queryset = pl_models.ApiKey.objects.select_related("usuario")

    def get_permissions(self):
        if self.action == "verify":
            self.required_role = []
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        entrada = api_keys_serializers.ApiKeyCreateSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario = get_object_or_404(
            pl_models.Usuario, pk=entrada.validated_data["usuario_id"]
        )

        clave, hash_, prefijo = api_keys_service.generar_clave()
        api_key = pl_models.ApiKey.objects.create(
            usuario=usuario,
            nombre=entrada.validated_data["nombre"],
            key_hash=hash_,
            key_prefix=prefijo,
            scopes=entrada.validated_data["scopes"],
        )
        datos = api_keys_serializers.ApiKeyCreadaSerializer(api_key).data
        datos["api_key"] = clave      # la única vez que sale en claro
        return Response(datos, status=201)

    @action(detail=False, methods=["get"], url_path=r"user/(?P<usuario_id>[^/.]+)")
    def user(self, request, usuario_id=None):
        usuario = get_object_or_404(pl_models.Usuario, pk=usuario_id)
        claves = self.get_queryset().filter(usuario=usuario).order_by("-created_at")
        return Response(self.get_serializer(claves, many=True).data)

    @action(detail=True, methods=["patch"], url_path="toggle")
    @log_endpoint(name="Operaciones | Plataforma | API keys | Toggle")
    def toggle(self, request, pk=None):
        api_key = self.get_object()
        api_key.activo = not api_key.activo
        api_key.save(update_fields=["activo"])
        return Response({"id": api_key.id, "activo": api_key.activo})

    @action(detail=False, methods=["get"], url_path="verify")
    def verify(self, request):
        """Comprueba que la credencial sirve. No requiere rol admin."""
        usuario = request.user.usuario
        return Response({
            "user_id": usuario.id,
            "nombre": usuario.nombre,
            "email": usuario.email,
            "rol": usuario.rol,
        })
