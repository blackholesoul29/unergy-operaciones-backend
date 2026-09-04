"""Modelos del dominio `energia`.

GENERADO por scripts/generar_modelos_django.py desde los metadatos de
SQLAlchemy. Es un BORRADOR: falta el verbose_name en español, los
TextChoices de las columnas de estado y los docstrings que explican el
modelo de datos. Revisar antes de portar la API del recurso.

`managed = False` en todos: mientras FastAPI siga leyendo estas tablas,
el único dueño del esquema es Alembic (ver apps/README.md).
"""

from django.db import models
from django.utils import timezone

from apps.plataforma.models import Timer

class ReporteEnergiaGeneracion(Timer):
    id = models.BigAutoField(primary_key=True)
    frontera = models.ForeignKey("fronteras.Frontera", on_delete=models.PROTECT, db_column="frontera_id", related_name="reporte_energia_generacion_por_frontera_id")
    fecha = models.DateField()
    caso = models.IntegerField()
    medidor_usado = models.CharField(max_length=30, null=True, blank=True)
    energia_final_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    curva_final = models.JSONField(null=True, blank=True)
    fp = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    fp_calculada = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    error_final_pct = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    energia_cgm_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    estado_reporte = models.CharField(max_length=20, null=True, blank=True)
    energia_solenium_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    solenium_completo = models.BooleanField(null=True, blank=True)
    nota_solenium = models.CharField(max_length=100, null=True, blank=True)
    energia_medidor_principal_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    energia_medidor_respaldo_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    medidor_principal_completo = models.BooleanField(null=True, blank=True)
    medidor_respaldo_completo = models.BooleanField(null=True, blank=True)
    curva_respaldo_terceros = models.JSONField(null=True, blank=True)
    curva_respaldo_final = models.JSONField(null=True, blank=True)
    respaldo_final_origen = models.CharField(max_length=20, null=True, blank=True)
    curva_medidor_principal = models.JSONField(null=True, blank=True)
    curva_medidor_respaldo = models.JSONField(null=True, blank=True)
    curva_solenium_referencia = models.JSONField(null=True, blank=True)
    curva_reconectador_referencia = models.JSONField(null=True, blank=True)
    horas_rellenadas_reconectador = models.JSONField(null=True, blank=True)
    horas_rellenadas_solenium = models.JSONField(null=True, blank=True)
    horas_rellenadas_historico = models.JSONField(null=True, blank=True)
    horas_rellenadas_medidor_cruzado = models.JSONField(null=True, blank=True)
    recuperacion_datos = models.CharField(max_length=255, null=True, blank=True)
    revisar_manualmente = models.BooleanField(default=False)
    editado_manualmente = models.BooleanField(default=False)
    error_clasificacion = models.CharField(max_length=500, null=True, blank=True)
    enviado_quoia_en = models.DateTimeField(null=True, blank=True)
    enviado_quoia_ok = models.BooleanField(null=True, blank=True)
    enviado_quoia_error = models.CharField(max_length=500, null=True, blank=True)
    xm_process_id = models.CharField(max_length=100, null=True, blank=True)
    xm_estado = models.CharField(max_length=30, null=True, blank=True)
    xm_exitoso = models.BooleanField(null=True, blank=True)
    xm_verificado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "reporte_energia_generacion"
        unique_together = [("fecha", "frontera")]


class ReporteEnergiaExclusion(models.Model):
    id = models.BigAutoField(primary_key=True)
    frontera = models.ForeignKey("fronteras.Frontera", on_delete=models.PROTECT, db_column="frontera_id", related_name="reporte_energia_exclusiones_por_frontera_id")
    motivo = models.CharField(max_length=500)
    fecha_inicio = models.DateField()
    fecha_fin_estimada = models.DateField(null=True, blank=True)
    creado_por = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="creado_por_id", related_name="reporte_energia_exclusiones_por_creado_por_id")
    resuelta_en = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "reporte_energia_exclusiones"


class ReporteEnergiaConsumo(Timer):
    id = models.BigAutoField(primary_key=True)
    frontera = models.ForeignKey("fronteras.Frontera", on_delete=models.PROTECT, db_column="frontera_id", related_name="reporte_energia_consumo_por_frontera_id")
    fecha = models.DateField()
    caso = models.CharField(max_length=20)
    medidor_usado = models.CharField(max_length=30, null=True, blank=True)
    energia_final_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    curva_final = models.JSONField(null=True, blank=True)
    energia_cgm_kwh = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    estado_reporte = models.CharField(max_length=20, null=True, blank=True)
    curva_medidor_principal = models.JSONField(null=True, blank=True)
    curva_medidor_respaldo = models.JSONField(null=True, blank=True)
    curva_respaldo_final = models.JSONField(null=True, blank=True)
    respaldo_final_origen = models.CharField(max_length=20, null=True, blank=True)
    horas_rellenadas_historico = models.JSONField(null=True, blank=True)
    horas_rellenadas_medidor_cruzado = models.JSONField(null=True, blank=True)
    recuperacion_datos = models.CharField(max_length=255, null=True, blank=True)
    revisar_manualmente = models.BooleanField(default=False)
    editado_manualmente = models.BooleanField(default=False)
    error_clasificacion = models.CharField(max_length=500, null=True, blank=True)
    enviado_quoia_en = models.DateTimeField(null=True, blank=True)
    enviado_quoia_ok = models.BooleanField(null=True, blank=True)
    enviado_quoia_error = models.CharField(max_length=500, null=True, blank=True)
    xm_process_id = models.CharField(max_length=100, null=True, blank=True)
    xm_estado = models.CharField(max_length=30, null=True, blank=True)
    xm_exitoso = models.BooleanField(null=True, blank=True)
    xm_verificado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "reporte_energia_consumo"
        unique_together = [("fecha", "frontera")]
