"""Serializers de generación diaria."""

from rest_framework import serializers

from apps.proyectos import models as py_models


class GeneracionSerializer(serializers.ModelSerializer):
    proyecto_id = serializers.IntegerField()
    proyecto_nombre = serializers.CharField(
        source="proyecto.nombre_comercial", read_only=True, allow_null=True
    )

    class Meta:
        model = py_models.GeneracionDiaria
        fields = [
            "id", "proyecto_id", "proyecto_nombre", "fecha", "kwh_real",
            "kwh_p90", "kwh_autoconsumo", "fuente", "notas",
            "created_at", "updated_at",
        ]


class GeneracionEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = py_models.GeneracionDiaria
        fields = [
            "proyecto", "fecha", "kwh_real", "kwh_p90", "kwh_autoconsumo",
            "fuente", "notas",
        ]
        extra_kwargs = {
            c: {"required": False} for c in fields
            if c not in ("proyecto", "fecha")
        }


class ItemBulkSerializer(serializers.Serializer):
    fecha = serializers.DateField()
    proyecto_id = serializers.IntegerField(required=False, allow_null=True)
    # El nombre del Excel; se resuelve por matching difuso si no viene el id.
    proyecto_nombre_externo = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    kwh_real = serializers.FloatField(required=False, allow_null=True)
    kwh_p90 = serializers.FloatField(required=False, allow_null=True)
    kwh_autoconsumo = serializers.FloatField(required=False, allow_null=True)
    fuente = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    notas = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class BulkSerializer(serializers.Serializer):
    items = ItemBulkSerializer(many=True)
    overwrite = serializers.BooleanField(default=False)
