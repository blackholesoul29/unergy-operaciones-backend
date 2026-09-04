"""Serializers de liquidaciones."""

from rest_framework import serializers

from apps.liquidaciones import models as lq_models


class LiquidacionSerializer(serializers.ModelSerializer):
    """El detalle operativo. **No trae costos, facturas ni mandatos**.

    El Estado de Resultados —del detalle y del PDF— es espejo del Panel
    Contable (`GET /liquidaciones/resumen-panel`); esos modelos se conservan
    pero ya no se sirven acá.
    """

    proyecto_id = serializers.IntegerField()
    proyecto_nombre = serializers.CharField(
        source="proyecto.nombre_comercial", read_only=True, allow_null=True
    )

    class Meta:
        model = lq_models.Liquidacion
        fields = [
            "id", "proyecto_id", "proyecto_nombre", "periodo", "tipo_venta",
            "estado", "fecha_inicio_proceso", "fecha_firma",
            "consecutivo_inicial_ingresos", "consecutivo_inicial_costos",
            "comprobante_contable_ref", "estado_resultados_url",
            "ingresos_energia_cop", "costos_comercializacion_xm_cop",
            "costos_operativos_cop", "ingreso_neto_cop", "tasa_cambio",
            "observaciones_resultados", "created_at", "updated_at",
        ]


class CrearSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    periodo = serializers.DateField()
    tipo_venta = serializers.CharField()
    observaciones_resultados = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )


class ActualizarSerializer(serializers.ModelSerializer):
    class Meta:
        model = lq_models.Liquidacion
        fields = [
            "estado", "estado_resultados_url", "fecha_inicio_proceso",
            "fecha_firma", "consecutivo_inicial_ingresos",
            "consecutivo_inicial_costos", "comprobante_contable_ref",
            "ingresos_energia_cop", "costos_comercializacion_xm_cop",
            "costos_operativos_cop", "ingreso_neto_cop", "tasa_cambio",
            "observaciones_resultados",
        ]
        extra_kwargs = {c: {"required": False} for c in fields}


class InformeSerializer(serializers.Serializer):
    html_content = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
