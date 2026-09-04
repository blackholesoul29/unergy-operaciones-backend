"""Serializers de facturación (solo los de escritura).

Las lecturas devuelven el dict que arma `apps/facturacion/services/calculo.py`
sin pasar por serializer: son estructuras anidadas que el frontend ya consume
tal cual, y declararlas campo por campo solo añadiría un sitio donde
desincronizarse.
"""

from rest_framework import serializers


class AgrupacionSerializer(serializers.Serializer):
    codigo_sic_contrato = serializers.CharField()
    # Vacío o nulo = quitar la asignación (el contrato vuelve a su PPA).
    nombre = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    # % del contrato que va a esta factura; el resto queda en el PPA.
    # Ej. Uruaco 78596 → 22.8066 % a "Terpel 1 Suno", 77.1934 % en Terpel 1.
    porcentaje = serializers.FloatField(
        required=False, allow_null=True, min_value=0.000001, max_value=100,
    )


class BolsaSerializer(serializers.Serializer):
    periodo = serializers.CharField()
    # Nulo o 0 = quitar el precio manual del mes.
    valor = serializers.FloatField(required=False, allow_null=True)


class OrdenSerializer(serializers.Serializer):
    # En el orden deseado; las que no vengan quedan al final.
    nombres = serializers.ListField(child=serializers.CharField(allow_blank=True))


class EmitidaSerializer(serializers.Serializer):
    nombre = serializers.CharField()
    periodo = serializers.CharField()
    emitida = serializers.BooleanField()
    numero_factura = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )

    def validate_nombre(self, valor):
        nombre = (valor or "").strip()
        if not nombre:
            raise serializers.ValidationError("Falta el nombre de la factura")
        return nombre
