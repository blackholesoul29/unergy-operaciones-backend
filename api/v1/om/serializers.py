"""Serializers del panel O&M mensual."""

from rest_framework import serializers

from apps.om import models as om_models


class ContratoOmSerializer(serializers.Serializer):
    contrato_id = serializers.IntegerField()
    proyecto_id = serializers.IntegerField(allow_null=True)
    nombre_proyecto = serializers.CharField()
    fecha_inicio = serializers.DateField(allow_null=True)
    valor_base_anual = serializers.FloatField(allow_null=True)
    estado = serializers.CharField()


class SeleccionSerializer(serializers.ModelSerializer):
    contrato_id = serializers.IntegerField()

    class Meta:
        model = om_models.OmSeleccionMensual
        fields = [
            "id", "contrato_id", "periodo", "incluido", "facturado",
            "valor_manual", "valor_facturado_congelado", "motivo_exclusion",
        ]


class SeleccionItemSerializer(serializers.Serializer):
    contrato_id = serializers.IntegerField()
    incluido = serializers.BooleanField()
    valor_manual = serializers.FloatField(required=False, allow_null=True)
    motivo_exclusion = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )


class GuardarSeleccionSerializer(serializers.Serializer):
    items = SeleccionItemSerializer(many=True)


class IpcTasaSerializer(serializers.ModelSerializer):
    class Meta:
        model = om_models.OmIpcTasa
        fields = ["id", "año", "tasa", "confirmado", "fuente"]


class IpcUpsertSerializer(serializers.Serializer):
    tasa = serializers.FloatField()
    confirmado = serializers.BooleanField(default=False)
    fuente = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class SinMatchAsignarSerializer(serializers.Serializer):
    contrato_id = serializers.IntegerField()


class EnlaceSerializer(serializers.Serializer):
    enlace_pdf = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    nombre_archivo = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
