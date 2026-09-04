"""Modelos del dominio `contabilidad`.

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

class PanelContable(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="panel_contable_por_proyecto_id")
    periodo = models.CharField(max_length=7)
    tipo = models.CharField(max_length=20, default="preliquidacion")
    liquidar = models.BooleanField(default=True)
    liquidar_ingresos = models.BooleanField(default=True)
    liquidar_costos = models.BooleanField(default=True)
    generar_mandatos = models.BooleanField(default=False)
    tiene_bolsa = models.BooleanField(default=False)
    tiene_costos = models.BooleanField(default=False)
    ingreso_bruto_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    comercializador = models.CharField(max_length=120, null=True, blank=True)
    fecha_firma = models.DateField(null=True, blank=True)
    consecutivo_ingresos = models.IntegerField(null=True, blank=True)
    consecutivo_costos = models.IntegerField(null=True, blank=True)
    origen = models.CharField(max_length=10, default="er")
    er_filename = models.CharField(max_length=300, null=True, blank=True)
    er_snapshot = models.TextField(null=True, blank=True)
    generado_por = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="generado_por_id", null=True, blank=True, related_name="panel_contable_por_generado_por_id")

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "panel_contable"
        unique_together = [("periodo", "proyecto", "tipo")]


class PanelContableLinea(models.Model):
    id = models.BigAutoField(primary_key=True)
    panel = models.ForeignKey("PanelContable", on_delete=models.CASCADE, db_column="panel_id", related_name="lineas")
    proyecto_inversionista = models.ForeignKey("proyectos.ProyectoInversionista", on_delete=models.SET_NULL, db_column="proyecto_inversionista_id", null=True, blank=True, related_name="panel_contable_linea_por_proyecto_inversionista_id")
    inversionista_nombre = models.CharField(max_length=255, null=True, blank=True)
    porcentaje = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    grupo = models.CharField(max_length=20)
    concepto = models.CharField(max_length=255)
    valor_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    comprobante_contable = models.CharField(max_length=120, null=True, blank=True)
    hoja = models.CharField(max_length=120, null=True, blank=True)
    celda = models.CharField(max_length=20, null=True, blank=True)
    fuente = models.CharField(max_length=20, null=True, blank=True)
    orden = models.IntegerField(default=0)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "panel_contable_linea"


class ClasificacionLiquidacion(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="clasificacion_liquidacion_por_proyecto_id")
    periodo = models.CharField(max_length=7)
    tipo = models.CharField(max_length=10, default="normal")

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "clasificacion_liquidacion"
        unique_together = [("periodo", "proyecto")]


class MapeoCeldaConcepto(models.Model):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="mapeo_celda_concepto_por_proyecto_id")
    concepto = models.CharField(max_length=255)
    hoja = models.CharField(max_length=120)
    celda = models.CharField(max_length=20)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "mapeo_celda_concepto"
        unique_together = [("concepto", "proyecto")]


class AliasFuenteIngreso(models.Model):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="alias_fuente_ingreso_por_proyecto_id")
    columna_origen = models.CharField(max_length=40)
    etiqueta = models.CharField(max_length=255)
    orden = models.IntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "alias_fuente_ingreso"
        unique_together = [("columna_origen", "proyecto")]


class PanelSoporte(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="panel_soporte_por_proyecto_id")
    periodo = models.CharField(max_length=7)
    tipo = models.CharField(max_length=20)
    grupo = models.CharField(max_length=20)
    concepto = models.CharField(max_length=255)
    archivo_url = models.CharField(max_length=1000)
    archivo_nombre = models.CharField(max_length=300, null=True, blank=True)
    drive_file_id = models.CharField(max_length=120, null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "panel_soporte"
        unique_together = [("concepto", "grupo", "periodo", "proyecto", "tipo")]


class PanelConsecutivo(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="panel_consecutivo_por_proyecto_id")
    periodo = models.CharField(max_length=7)
    tipo = models.CharField(max_length=20)
    proyecto_inversionista = models.ForeignKey("proyectos.ProyectoInversionista", on_delete=models.SET_NULL, db_column="proyecto_inversionista_id", null=True, blank=True, related_name="panel_consecutivo_por_proyecto_inversionista_id")
    inversionista_nombre = models.CharField(max_length=255)
    consecutivo_ingresos = models.IntegerField(null=True, blank=True)
    consecutivo_costos = models.IntegerField(null=True, blank=True)

    class Meta:
        managed = False        # el esquema lo posee Alembic
        db_table = "panel_consecutivo"
        unique_together = [("inversionista_nombre", "periodo", "proyecto", "tipo")]
