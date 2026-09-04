"""Modelos del dominio `retos`.

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

class RetoTrimestre(Timer):
    id = models.BigAutoField(primary_key=True)
    anio = models.IntegerField(db_index=True)
    trimestre = models.IntegerField()
    nombre = models.CharField(max_length=160, null=True, blank=True)
    descripcion = models.TextField(null=True, blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

    class Meta:
        db_table = "retos_trimestre"
        unique_together = [("anio", "trimestre")]


class RetoMetrica(Timer):
    id = models.BigAutoField(primary_key=True)
    reto = models.ForeignKey("RetoTrimestre", on_delete=models.CASCADE, db_column="reto_id", related_name="metricas")
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(null=True, blank=True)
    unidad = models.CharField(max_length=40, null=True, blank=True)
    meta = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    tipo_agregacion = models.CharField(max_length=20, default="suma")
    direccion = models.CharField(max_length=20, default="mayor_mejor")
    decimales = models.IntegerField(default=0)
    responsable = models.CharField(max_length=120, null=True, blank=True)
    orden = models.IntegerField(default=0)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = "retos_metrica"


class RetoValorSemanal(Timer):
    id = models.BigAutoField(primary_key=True)
    metrica = models.ForeignKey("RetoMetrica", on_delete=models.CASCADE, db_column="metrica_id", related_name="valores")
    semana_inicio = models.DateField()
    valor = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    nota = models.TextField(null=True, blank=True)
    actualizado_por = models.ForeignKey("plataforma.Usuario", on_delete=models.SET_NULL, db_column="actualizado_por_id", null=True, blank=True, related_name="retos_valor_semanal_por_actualizado_por_id")

    class Meta:
        db_table = "retos_valor_semanal"
        unique_together = [("metrica", "semana_inicio")]
