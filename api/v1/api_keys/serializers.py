"""Serializers de claves de API."""

from rest_framework import serializers

from apps.plataforma import models as pl_models


class ApiKeySerializer(serializers.ModelSerializer):
    """Lectura. NUNCA expone `key_hash` ni la clave en claro."""

    usuario_id = serializers.IntegerField()
    usuario_nombre = serializers.CharField(source="usuario.nombre", read_only=True)
    scopes = serializers.SerializerMethodField()

    class Meta:
        model = pl_models.ApiKey
        fields = [
            "id", "usuario_id", "usuario_nombre", "nombre", "key_prefix",
            "scopes", "activo", "ultimo_uso", "expires_at", "created_at",
        ]

    def get_scopes(self, obj) -> list:
        # El DDL pone '["read"]' por defecto, pero una fila vieja puede traer
        # NULL; el contrato siempre devuelve al menos ["read"].
        return obj.scopes or ["read"]


class ApiKeyCreadaSerializer(ApiKeySerializer):
    """La respuesta del POST: igual que la lectura MÁS la clave en claro.

    Es la única vez que `api_key` sale en una respuesta.
    """

    api_key = serializers.CharField(read_only=True)

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ["api_key"]


class ApiKeyCreateSerializer(serializers.Serializer):
    usuario_id = serializers.IntegerField()
    nombre = serializers.CharField(max_length=255)
    scopes = serializers.ListField(child=serializers.CharField(), default=["read"])
