"""Serializers del tablero de retos — uno por direccion, uno por granularidad.

El contrato de salida es el que ya consume el frontend (los schemas Pydantic de
`app/schemas/retos.py`). Los campos calculados (`consolidado`, `estado`,
`serie`, …) los anota `queryset.py` sobre la instancia; aca se leen por su
nombre igual que cualquier columna real.
"""

from rest_framework import serializers

from api.fields import RoundedDecimalField
from apps.retos import models as rt_models


class SeriePuntoSerializer(serializers.Serializer):
    semana = serializers.IntegerField()
    valor = serializers.FloatField(allow_null=True)


class SemanaSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    inicio = serializers.DateField()
    fin = serializers.DateField()
    inicio_efectivo = serializers.DateField()
    fin_efectivo = serializers.DateField()
    etiqueta = serializers.CharField()
    rango_label = serializers.CharField()
    es_actual = serializers.BooleanField()
    es_futura = serializers.BooleanField()
    parcial = serializers.BooleanField()


class MetricaResumenSerializer(serializers.ModelSerializer):
    """Lectura de una metrica con su calculo. Todo lo derivado viene anotado."""

    reto_id = serializers.IntegerField()
    meta = serializers.FloatField(source="meta_num", allow_null=True)
    consolidado = serializers.FloatField(allow_null=True)
    meta_esperada = serializers.FloatField(allow_null=True)
    avance_pct = serializers.FloatField(allow_null=True)
    cumplimiento_pct = serializers.FloatField(allow_null=True)
    estado = serializers.CharField()
    semanas_con_dato = serializers.IntegerField()
    serie = SeriePuntoSerializer(many=True)

    class Meta:
        model = rt_models.RetoMetrica
        fields = [
            "id", "reto_id", "nombre", "descripcion", "unidad", "meta",
            "tipo_agregacion", "direccion", "decimales", "responsable", "orden",
            "activa", "consolidado", "meta_esperada", "avance_pct",
            "cumplimiento_pct", "estado", "semanas_con_dato", "serie",
        ]


class RetoResumenSerializer(serializers.ModelSerializer):
    metricas = MetricaResumenSerializer(source="metricas_anotadas", many=True)
    total_semanas = serializers.IntegerField()
    semana_actual = serializers.IntegerField(allow_null=True)
    estado_periodo = serializers.CharField()
    total_metricas = serializers.IntegerField()
    semanas_con_datos = serializers.IntegerField()
    avance_global_pct = serializers.FloatField(allow_null=True)

    class Meta:
        model = rt_models.RetoTrimestre
        fields = [
            "id", "anio", "trimestre", "nombre", "descripcion", "fecha_inicio",
            "fecha_fin", "total_semanas", "semana_actual", "estado_periodo",
            "total_metricas", "semanas_con_datos", "avance_global_pct", "metricas",
        ]


class RetoDetalleSerializer(RetoResumenSerializer):
    """El resumen + las semanas generadas y la matriz de valores.

    Subclase en vez de copia: asi el listado y el detalle no se desincronizan
    cuando se agrega un campo al resumen.
    """

    semanas = SemanaSerializer(many=True)
    valores = serializers.DictField()

    class Meta(RetoResumenSerializer.Meta):
        fields = RetoResumenSerializer.Meta.fields + ["semanas", "valores"]


class RetosAnioSerializer(serializers.Serializer):
    """La envoltura del listado. `GET /retos` NO devuelve una lista paginada."""

    anio = serializers.IntegerField()
    anios_disponibles = serializers.ListField(child=serializers.IntegerField())
    retos = RetoResumenSerializer(many=True)


# ---------------------------------------------------------------------------
# Escritura — serializers aparte de los de lectura
# ---------------------------------------------------------------------------

class RetoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = rt_models.RetoTrimestre
        fields = ["nombre", "descripcion", "fecha_inicio", "fecha_fin"]
        extra_kwargs = {f: {"required": False} for f in fields}

    def validate(self, data):
        from apps.retos.services import calculo as svc

        inicio = data.get("fecha_inicio") or self.instance.fecha_inicio
        fin = data.get("fecha_fin") or self.instance.fecha_fin
        if fin <= inicio:
            raise serializers.ValidationError(
                "La fecha de fin debe ser posterior a la de inicio"
            )
        if svc.contar_semanas(inicio, fin) > svc.TOPE_SEMANAS:
            raise serializers.ValidationError(
                f"El rango no puede superar {svc.TOPE_SEMANAS} semanas"
            )
        return data


class MetricaCreateSerializer(serializers.ModelSerializer):
    meta = RoundedDecimalField(required=False, allow_null=True)
    orden = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = rt_models.RetoMetrica
        fields = [
            "nombre", "descripcion", "unidad", "meta", "tipo_agregacion",
            "direccion", "decimales", "responsable", "orden",
        ]

    def validate_decimales(self, value):
        return max(0, min(4, int(value)))


class MetricaUpdateSerializer(MetricaCreateSerializer):
    class Meta(MetricaCreateSerializer.Meta):
        fields = MetricaCreateSerializer.Meta.fields + ["activa"]
        extra_kwargs = {f: {"required": False} for f in fields}


class ValorSemanalSerializer(serializers.ModelSerializer):
    valor = RoundedDecimalField(required=False, allow_null=True)

    class Meta:
        model = rt_models.RetoValorSemanal
        fields = ["valor", "nota"]
