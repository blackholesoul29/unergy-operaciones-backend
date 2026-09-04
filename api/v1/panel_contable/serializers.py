"""Serializers del Panel Contable.

Solo entrada: las respuestas las arma `apps.contabilidad.services.panel`, que
devuelve dicts ya con la forma que sirve FastAPI hoy. Meterlos en un
ModelSerializer los reescribiría y rompería la paridad.
"""

from rest_framework import serializers

TIPO_DEFECTO = "preliquidacion"


class CargarPeriodoSerializer(serializers.Serializer):
    """Período a armar. `version` es la de XM (txf, tx3…tx8)."""

    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default="oficial")
    version = serializers.CharField(required=False, default="txf")


class AsignacionClasifSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    tipo = serializers.CharField()  # 'normal' | 'neu' | 'nitro'


class ClasificacionSerializer(serializers.Serializer):
    periodo = serializers.CharField()
    asignaciones = AsignacionClasifSerializer(many=True)


class LineaPatchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    valor_cop = serializers.FloatField(required=False, allow_null=True)
    comprobante_contable = serializers.CharField(
        required=False, allow_null=True, allow_blank=True)
    concepto = serializers.CharField(
        required=False, allow_null=True, allow_blank=True)


class PanelPatchSerializer(serializers.Serializer):
    liquidar = serializers.BooleanField(required=False, allow_null=True)
    liquidar_ingresos = serializers.BooleanField(required=False, allow_null=True)
    liquidar_costos = serializers.BooleanField(required=False, allow_null=True)
    generar_mandatos = serializers.BooleanField(required=False, allow_null=True)
    fecha_firma = serializers.DateField(required=False, allow_null=True)
    consecutivo_ingresos = serializers.IntegerField(required=False, allow_null=True)
    consecutivo_costos = serializers.IntegerField(required=False, allow_null=True)
    lineas = LineaPatchSerializer(many=True, required=False, allow_null=True)


class RedividirSerializer(serializers.Serializer):
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    proyecto_id = serializers.IntegerField(required=False, allow_null=True,
                                           default=None)
    # forzar=True re-divide aun si los % parecen correctos (pisa ediciones manuales).
    forzar = serializers.BooleanField(required=False, default=False)


class MapeoCeldaSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    concepto = serializers.CharField()
    hoja = serializers.CharField()
    celda = serializers.CharField()


class AliasFuenteSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    columna_origen = serializers.CharField()   # "Sheet1!G35"
    etiqueta = serializers.CharField()         # ej. "Ingreso Bruto Terpel 1"
    orden = serializers.IntegerField(required=False, allow_null=True, default=None)


class FuenteIngresoSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    etiqueta = serializers.CharField()
    hoja = serializers.CharField()
    celda = serializers.CharField()
    orden = serializers.IntegerField(required=False, allow_null=True, default=None)


class QuitarFuenteIngresoSerializer(serializers.Serializer):
    proyecto_id = serializers.IntegerField()
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    columna_origen = serializers.CharField()   # "Sheet1!G35" — la fuente a quitar


class ReasignarConsecutivosSerializer(serializers.Serializer):
    periodo = serializers.CharField()
    tipo = serializers.CharField(required=False, default=TIPO_DEFECTO)
    consecutivo_ingresos_inicial = serializers.IntegerField()
    consecutivo_costos_inicial = serializers.IntegerField()
    # solo_faltantes=True: NO renumera todo; solo rellena los consecutivos que
    # están en None (preservando los ya asignados / editados a mano). Se usa al
    # cargar la vista para que todo panel marcado quede numerado sin pisar
    # ediciones manuales. False (default): renumeración completa desde el inicial.
    solo_faltantes = serializers.BooleanField(required=False, default=False)
