"""Serializers de verificación de costos."""

from rest_framework import serializers

from api.fields import RoundedDecimalField
from apps.proyectos import models as py_models


class VerificacionCostoSerializer(serializers.ModelSerializer):
    """Lectura. `proyecto_nombre` viene anotado por el queryset, no por una
    consulta por fila."""

    proyecto_id = serializers.IntegerField()
    proyecto_nombre = serializers.CharField(read_only=True, default="")
    costos_generador = RoundedDecimalField(decimal_places=2, allow_null=True)
    costos_comercializador = RoundedDecimalField(decimal_places=2, allow_null=True)
    ac_power = RoundedDecimalField(decimal_places=4, allow_null=True)

    class Meta:
        model = py_models.VerificacionCosto
        fields = [
            "id", "proyecto_id", "proyecto_nombre", "costos_generador",
            "costos_comercializador", "ac_power", "created_at", "updated_at",
        ]


class VerificacionCostoCreateSerializer(serializers.ModelSerializer):
    proyecto_id = serializers.PrimaryKeyRelatedField(
        source="proyecto", queryset=py_models.Proyecto.objects.all(), write_only=True
    )

    class Meta:
        model = py_models.VerificacionCosto
        fields = [
            "proyecto_id", "costos_generador", "costos_comercializador", "ac_power",
        ]

    def validate_proyecto_id(self, proyecto):
        # Una verificación por proyecto: el contrato responde 409, no 400.
        if py_models.VerificacionCosto.objects.filter(proyecto=proyecto).exists():
            raise serializers.ValidationError(
                "Ya existe una verificación de costos para este proyecto",
                code="conflict",
            )
        return proyecto


class VerificacionCostoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = py_models.VerificacionCosto
        fields = ["costos_generador", "costos_comercializador", "ac_power"]
        extra_kwargs = {f: {"required": False} for f in fields}
