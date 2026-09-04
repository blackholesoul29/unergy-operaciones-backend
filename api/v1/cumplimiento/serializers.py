"""Las dos ÚNICAS entradas de Cumplimiento: cerrar un período y facturarlo.

Los otros 22 endpoints son GET y sus parámetros se validan en la vista con
`api/v1/cumplimiento/parametros.py` — declarar un serializer por query string
sería más código que el que valida.
"""

from rest_framework import serializers


class CerrarPeriodoSerializer(serializers.Serializer):
    anio = serializers.IntegerField(min_value=2020, max_value=2050)
    mes = serializers.IntegerField(min_value=1, max_value=12)


class FacturarSerializer(serializers.Serializer):
    liquidacion_id = serializers.IntegerField(required=False, allow_null=True, default=None)
