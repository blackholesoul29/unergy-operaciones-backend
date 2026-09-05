"""Serializers del impacto de mantenimiento."""

from rest_framework import serializers

from apps.monitoreo import models as mo_models


class ImpactoSerializer(serializers.ModelSerializer):
    """Las métricas son de solo lectura: las calcula el servicio."""

    proyecto_id = serializers.IntegerField()
    proyecto_nombre = serializers.CharField(
        source="proyecto.nombre_comercial", read_only=True, allow_null=True
    )
    falla_id = serializers.IntegerField(allow_null=True)

    class Meta:
        model = mo_models.MantenimientoImpacto
        fields = [
            "id", "proyecto_id", "proyecto_nombre", "falla_id",
            "maintenance_type", "start_time", "end_time", "duration_hours",
            "expected_generation_kwh", "actual_generation_kwh",
            "lost_energy_kwh", "financial_impact_cop",
            "ppa_penalty_risk_flag", "created_by", "created_at", "updated_at",
        ]


class ImpactoEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = mo_models.MantenimientoImpacto
        fields = [
            "proyecto", "falla", "maintenance_type", "start_time", "end_time",
            "expected_generation_kwh", "actual_generation_kwh",
        ]
        extra_kwargs = {
            c: {"required": False} for c in fields
            if c not in ("proyecto", "start_time", "end_time")
        }

    def validate(self, datos):
        inicio = datos.get("start_time") or getattr(
            self.instance, "start_time", None
        )
        fin = datos.get("end_time") or getattr(self.instance, "end_time", None)
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError(
                "end_time no puede ser anterior a start_time"
            )
        return datos
