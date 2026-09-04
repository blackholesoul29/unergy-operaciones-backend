"""Serializers de portafolios."""

from rest_framework import serializers

from apps.proyectos import models as py_models


class ProyectoEnPortafolioSerializer(serializers.ModelSerializer):
    """El proyecto reducido a lo que la pantalla de capas necesita mostrar."""

    nombre = serializers.CharField(source="nombre_comercial", allow_null=True)

    class Meta:
        model = py_models.Proyecto
        fields = ["id", "nombre", "sub_project", "municipio"]


class PortafolioSerializer(serializers.ModelSerializer):
    proyectos = ProyectoEnPortafolioSerializer(many=True, read_only=True)

    class Meta:
        model = py_models.Portafolio
        fields = ["id", "nombre", "activo", "proyectos"]


class PortafolioCreateSerializer(serializers.Serializer):
    nombre = serializers.CharField()

    def validate_nombre(self, valor):
        nombre = (valor or "").strip()
        if not nombre:
            raise serializers.ValidationError(
                "El nombre del portafolio no puede estar vacío"
            )
        return nombre


class PortafolioUpdateSerializer(serializers.Serializer):
    nombre = serializers.CharField(required=False)
    activo = serializers.BooleanField(required=False)

    def validate_nombre(self, valor):
        nombre = (valor or "").strip()
        if not nombre:
            raise serializers.ValidationError("El nombre no puede estar vacío")
        return nombre


class AsignarSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    # null = quitar el proyecto de su portafolio (queda en el pool).
    portafolio_id = serializers.IntegerField(required=False, allow_null=True)
