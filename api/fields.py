"""Campos de serializer reusables.

Portados de `api/fields.py` de Origina, con dos ausencias deliberadas:
`FileValueField` y `FileWithStatusField` quedan fuera porque alli resuelven URLs
contra Backblaze B2 y este backend usa S3 (`S3_*` en el .env). Cuando haga falta
el equivalente, va contra el cliente de S3 de este repo, no copiado.

Antes de escribir un `SerializerMethodField`, buscar si el campo ya esta aca.
"""

from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers


class CentsField(serializers.IntegerField):
    """Centavos en la base, pesos en el JSON.

    **Convierte solo de salida, a proposito.** El serializer de escritura hace
    `validated_data["campo"] * 100` a mano. La asimetria es de Origina y no hay
    que "arreglarla": un campo simetrico convierte dos veces en cuanto un
    service tambien multiplica, y el error es silencioso.
    """

    def to_representation(self, value):
        if value is None:
            return None
        return float(Decimal(value) / 100)


class ChoiceDisplayField(serializers.Field):
    """`"paid"` -> `{"value": "paid", "display": "Pagado"}`.

    Si la columna puede ser NULL hay que pasar `allow_null=True`: sin eso DRF
    levanta `SkipField` y la clave DESAPARECE del JSON en vez de salir en null.
    Un cliente que lee `obj.estado.value` revienta con KeyError, no con None.
    """

    def __init__(self, choices, **kwargs):
        self.choices = dict(choices)
        kwargs.setdefault("read_only", True)
        super().__init__(**kwargs)

    def to_representation(self, value):
        if value is None:
            return None
        return {"value": value, "display": self.choices.get(value, value)}


class YesNoBooleanField(serializers.BooleanField):
    """bool <-> "si"/"no"."""

    def to_representation(self, value):
        return "si" if value else "no"

    def to_internal_value(self, data):
        if isinstance(data, str):
            return data.strip().lower() in ("si", "sí", "true", "1")
        return super().to_internal_value(data)


class SafeIntegerField(serializers.IntegerField):
    """Entero tolerante a "" y None, para entradas de CSV y APIs externas."""

    def to_internal_value(self, data):
        if data in ("", None):
            return None
        return super().to_internal_value(data)


class RoundedDecimalField(serializers.DecimalField):
    """Numeric de la base -> float redondeado en el JSON.

    No existe en Origina: aca hace falta porque buena parte del esquema usa
    `Numeric(20, 4)` y el contrato actual de FastAPI devuelve numeros, no las
    cadenas que DRF produce por defecto con DecimalField.
    """

    def __init__(self, max_digits=20, decimal_places=4, **kwargs):
        kwargs.setdefault("coerce_to_string", False)
        super().__init__(max_digits=max_digits, decimal_places=decimal_places, **kwargs)

    def to_representation(self, value):
        if value is None:
            return None
        quant = Decimal(1).scaleb(-self.decimal_places)
        return float(Decimal(value).quantize(quant, rounding=ROUND_HALF_UP))
