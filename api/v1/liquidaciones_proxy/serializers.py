"""Serializers del proxy de Liquidaciones.

Casi todas las respuestas son dicts que arma
`apps/liquidaciones/services/agregados.py` y viajan tal cual: son la traducción
de lo que devuelve una API externa, y volver a declararlas campo por campo solo
añadiría un sitio donde desincronizarse. Acá van únicamente las de ESCRITURA,
que sí hay que validar antes de mandar nada afuera.
"""

from rest_framework import serializers

VERSIONES = ("txf", "txr", "tx2", "tx3", "tx4", "tx5", "tx6", "tx7", "tx8")


class ProyectoUpdateSerializer(serializers.Serializer):
    """Los campos de configuración que la API externa acepta actualizar."""

    codigo_sic = serializers.CharField(required=False, allow_null=True)
    codigo_frt = serializers.CharField(required=False, allow_null=True)
    ac_power = serializers.FloatField(required=False, allow_null=True)
    es_generador = serializers.BooleanField(required=False)
    es_comercializador = serializers.BooleanField(required=False)


class SubproyectoUpdateSerializer(serializers.Serializer):
    """Los tres ids de Quoia.

    Se manda solo lo que venga (`partial`): en esta API enviar `null` **borra**
    el id, así que un campo omitido y uno vacío NO significan lo mismo.
    """

    quoia_report_id = serializers.CharField(required=False, allow_null=True)
    quoia_report_id_2 = serializers.CharField(required=False, allow_null=True)
    quoia_node_id = serializers.CharField(required=False, allow_null=True)


class PeriodoSerializer(serializers.Serializer):
    month = serializers.IntegerField(min_value=1, max_value=12)
    year = serializers.IntegerField(min_value=2020, max_value=2100)
    version = serializers.ChoiceField(choices=VERSIONES, default="txf")


class RepartoSerializer(PeriodoSerializer):
    total_ac_power = serializers.FloatField()
    override = serializers.BooleanField(default=False)
    last_version = serializers.ChoiceField(
        choices=VERSIONES, required=False, allow_null=True
    )


class DiagnosticoSerializer(PeriodoSerializer):
    project = serializers.CharField()


class ProyectoDeContratoSerializer(serializers.Serializer):
    project = serializers.CharField()
    energy_price = serializers.IntegerField(required=False, allow_null=True)
    floor = serializers.FloatField(required=False, allow_null=True)
    roof = serializers.FloatField(required=False, allow_null=True)


class ContratoEnergiaSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    code = serializers.CharField()
    contract_type = serializers.CharField()
    tariff_price_type = serializers.CharField(required=False, allow_null=True)
    percentage = serializers.FloatField(required=False, allow_null=True)
    company = serializers.IntegerField()
    proyectos = ProyectoDeContratoSerializer(many=True, default=list)
