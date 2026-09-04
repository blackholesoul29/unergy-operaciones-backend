"""Serializers de contratos de servicio, sus facturas y sus pagos."""

from rest_framework import serializers

from apps.contratos import models as ct_models
from apps.facturacion import models as fa_models


class ContratoSerializer(serializers.ModelSerializer):
    proyecto_id = serializers.IntegerField(allow_null=True)
    contratante_id = serializers.IntegerField(allow_null=True)
    prestador_id = serializers.IntegerField(allow_null=True)
    inversionista_id = serializers.IntegerField(allow_null=True)
    portafolio_id = serializers.IntegerField(allow_null=True)
    nombre_proyecto = serializers.SerializerMethodField()
    frontera_ids = serializers.SerializerMethodField()
    enlace_drive = serializers.SerializerMethodField()

    class Meta:
        model = ct_models.ContratoServicio
        exclude = [
            "proyecto", "contratante", "prestador", "inversionista",
            "portafolio",
        ]

    def get_nombre_proyecto(self, obj) -> str | None:
        return obj.proyecto.nombre_comercial if obj.proyecto else None

    def get_frontera_ids(self, obj) -> list[int]:
        return [
            v.frontera_id
            for v in obj.contrato_frontera_por_contrato_servicio_id.all()
        ]

    def get_enlace_drive(self, obj) -> str | None:
        """El enlace vive como documento comercial `tipo='contrato'`.

        Se lee de la relación YA precargada; buscarlo por fila sería un N+1.
        """
        for documento in obj.cliente_documentos_comerciales_por_contrato_servicio_id.all():
            if documento.tipo == "contrato" and documento.archivo_url:
                return documento.archivo_url
        return None


class ContratoEscrituraSerializer(serializers.ModelSerializer):
    frontera_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )
    enlace_drive = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = ct_models.ContratoServicio
        fields = "__all__"
        extra_kwargs = {"servicio_aplica": {"required": False}}


class FacturaSerializer(serializers.ModelSerializer):
    contrato_id = serializers.IntegerField(read_only=True)
    inversionista_id = serializers.IntegerField(allow_null=True, required=False)

    class Meta:
        model = fa_models.ContratoFactura
        fields = [
            "id", "contrato_id", "tipo", "fecha", "inversionista_id",
            "numero_factura", "monto", "enlace_soporte",
            "created_at", "updated_at",
        ]


class FacturaEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = fa_models.ContratoFactura
        fields = [
            "tipo", "fecha", "inversionista", "numero_factura", "monto",
            "enlace_soporte",
        ]
        extra_kwargs = {c: {"required": False} for c in fields}


class PagoSerializer(serializers.ModelSerializer):
    contrato_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ct_models.PagoServicio
        fields = [
            "id", "contrato_id", "año", "mes", "valor_pagado", "estado",
            "enlace_factura", "created_at", "updated_at",
        ]


class PagoEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = ct_models.PagoServicio
        fields = ["año", "mes", "valor_pagado", "estado", "enlace_factura"]
        extra_kwargs = {c: {"required": False} for c in fields}


class FilaIndexacionSerializer(serializers.Serializer):
    anio = serializers.IntegerField()
    ipc_aplicado = serializers.FloatField(allow_null=True, required=False)
    valor = serializers.FloatField(allow_null=True, required=False)


class ImportarIndexacionSerializer(serializers.Serializer):
    proyecto = serializers.CharField()
    filas = FilaIndexacionSerializer(many=True)


class FusionarSerializer(serializers.Serializer):
    # `null` o ausente = fusionar todos los grupos limpios.
    ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )
