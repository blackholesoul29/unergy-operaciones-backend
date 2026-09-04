"""Serializers del historial de ajustes de garantías XM.

Los doce montos se declaran uno por uno con `RoundedDecimalField`: salen como
número en el JSON y no como la cadena que DRF produce por defecto con
`DecimalField`. Es el contrato que ya consume el frontend.
"""

from rest_framework import serializers

from api.fields import RoundedDecimalField
from apps.garantias import models as ga_models


def _monto():
    return RoundedDecimalField(decimal_places=2, required=False, allow_null=True)


class GarantiaAjusteSerializer(serializers.ModelSerializer):
    pb = _monto()
    restricciones = _monto()
    stn = _monto()
    trm = _monto()
    ptb = _monto()
    total_ungc = _monto()
    total_ungg = _monto()
    total_consignar = _monto()
    disponible_custodia = _monto()
    congelado = _monto()
    saldo = _monto()
    total_ajuste_txr = _monto()

    class Meta:
        model = ga_models.GarantiaAjuste
        fields = [
            "id", "tipo", "fecha", "pb", "restricciones", "stn", "trm", "ptb",
            "total_ungc", "total_ungg", "total_consignar", "disponible_custodia",
            "congelado", "saldo", "total_ajuste_txr", "snapshot",
            "created_at", "updated_at",
        ]


class GarantiaAjusteEscrituraSerializer(GarantiaAjusteSerializer):
    """Los campos declarados arriba se heredan; solo cambia qué se acepta."""

    class Meta(GarantiaAjusteSerializer.Meta):
        fields = [
            f for f in GarantiaAjusteSerializer.Meta.fields
            if f not in ("id", "created_at", "updated_at")
        ]


class GarantiaAjusteUpdateSerializer(GarantiaAjusteEscrituraSerializer):
    class Meta(GarantiaAjusteEscrituraSerializer.Meta):
        extra_kwargs = {
            "tipo": {"required": False},
            "fecha": {"required": False},
            "snapshot": {"required": False},
        }
