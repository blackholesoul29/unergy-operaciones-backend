"""Modelos del dominio `liquidaciones`.

GENERADO por scripts/generar_modelos_django.py desde los metadatos de
SQLAlchemy. Es un BORRADOR: falta el verbose_name en español, los
TextChoices de las columnas de estado y los docstrings que explican el
modelo de datos. Revisar antes de portar la API del recurso.

Django posee el esquema de estas tablas desde el 2026-09-04. Los modelos son
`managed` (el default): `makemigrations` genera DDL real y `migrate` lo aplica.
Alembic quedo congelado en la revision 143 -- ver apps/README.md.
"""

from django.db import models

from apps.plataforma.models import Timer

class Liquidacion(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.DO_NOTHING, db_column="proyecto_id", related_name="liquidaciones_por_proyecto_id")
    generado_por = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="generado_por_id", related_name="liquidaciones_por_generado_por_id")
    periodo = models.DateField()
    tipo_venta = models.CharField(max_length=11, choices=[("bolsa", "bolsa"), ("ppa", "ppa"), ("interno", "interno"), ("autoconsumo", "autoconsumo")])
    estado = models.CharField(max_length=18, choices=[("iniciada", "iniciada"), ("costos_registrados", "costos_registrados"), ("xm_procesado", "xm_procesado"), ("mandatos_emitidos", "mandatos_emitidos"), ("en_contabilidad", "en_contabilidad"), ("en_revisoria", "en_revisoria"), ("facturado", "facturado"), ("entregado", "entregado")], default="iniciada")
    fecha_inicio_proceso = models.DateField(null=True, blank=True)
    fecha_firma = models.DateField(null=True, blank=True)
    consecutivo_inicial_ingresos = models.IntegerField(null=True, blank=True)
    consecutivo_inicial_costos = models.IntegerField(null=True, blank=True)
    comprobante_contable_ref = models.CharField(max_length=50, null=True, blank=True)
    estado_resultados_url = models.CharField(max_length=1000, null=True, blank=True)
    ingresos_energia_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    costos_comercializacion_xm_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    costos_operativos_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ingreso_neto_cop = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    ingreso_neto_usd = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    tasa_cambio = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    observaciones_resultados = models.TextField(null=True, blank=True)
    informe_html = models.TextField(null=True, blank=True)
    informe_actualizado_en = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "liquidaciones"
        unique_together = [("periodo", "proyecto")]


class LiquidacionCosto(Timer):
    id = models.BigAutoField(primary_key=True)
    liquidacion = models.ForeignKey("Liquidacion", on_delete=models.DO_NOTHING, db_column="liquidacion_id", related_name="costos")
    tipo_costo = models.CharField(max_length=21, choices=[("mantenimiento", "mantenimiento"), ("internet", "internet"), ("arriendo", "arriendo"), ("polizas", "polizas"), ("comercializacion_xm", "comercializacion_xm"), ("servicios_publicos", "servicios_publicos"), ("cambio_equipos_medida", "cambio_equipos_medida"), ("otro", "otro")])
    descripcion = models.CharField(max_length=500)
    proveedor = models.CharField(max_length=255, null=True, blank=True)
    nro_soporte = models.CharField(max_length=100, null=True, blank=True)
    soporte_url = models.CharField(max_length=1000, null=True, blank=True)
    valor_cop = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = "liquidacion_costos"


class LiquidacionFactura(Timer):
    id = models.BigAutoField(primary_key=True)
    liquidacion = models.ForeignKey("Liquidacion", on_delete=models.DO_NOTHING, db_column="liquidacion_id", related_name="facturas")
    proyecto_inversionista = models.ForeignKey("proyectos.ProyectoInversionista", on_delete=models.SET_NULL, db_column="proyecto_inversionista_id", null=True, blank=True, related_name="liquidacion_facturas_por_proyecto_inversionista_id")
    tipo_servicio = models.CharField(max_length=24, choices=[("representacion", "representacion"), ("cgm", "cgm"), ("administracion_operacion", "administracion_operacion")])
    numero_factura = models.CharField(max_length=100, null=True, blank=True)
    nro_soporte = models.CharField(max_length=100, null=True, blank=True)
    soporte_url = models.CharField(max_length=1000, null=True, blank=True)
    valor_cop = models.DecimalField(max_digits=18, decimal_places=2)
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=7, choices=[("emitida", "emitida"), ("pagada", "pagada"), ("vencida", "vencida")], default="emitida")

    class Meta:
        db_table = "liquidacion_facturas"
