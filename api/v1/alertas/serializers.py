"""Serializers de alertas."""

from rest_framework import serializers

from apps.monitoreo import models as mo_models


class AlertaSerializer(serializers.ModelSerializer):
    """La alerta persistida por el job de vencimientos PPA."""

    class Meta:
        model = mo_models.Alerta
        fields = [
            "id", "ppa_id", "project_id", "alert_type", "description",
            "due_date", "trigger_date", "days_to_expiration", "status",
            "created_at", "updated_at",
        ]


class ActualizarEstadoSerializer(serializers.Serializer):
    """No hay vocabulario cerrado de estados: hoy el job solo emite 'new' y la
    pantalla escribe 'revisada' o 'descartada'. Se acepta texto libre a
    propósito, igual que hoy."""

    status = serializers.CharField()
