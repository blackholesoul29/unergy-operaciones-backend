"""Serializers de notificaciones."""

from rest_framework import serializers

from apps.plataforma import models as pl_models


class NotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = pl_models.Notificacion
        fields = ["id", "usuario_id", "tipo", "titulo", "mensaje", "leida", "created_at"]
