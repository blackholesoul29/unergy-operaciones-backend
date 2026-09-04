"""Modelos del dominio `registros_cnd`.

GENERADO por scripts/generar_modelos_django.py desde los metadatos de
SQLAlchemy. Es un BORRADOR: falta el verbose_name en español, los
TextChoices de las columnas de estado y los docstrings que explican el
modelo de datos. Revisar antes de portar la API del recurso.

Django posee el esquema de estas tablas desde el 2026-09-04. Los modelos son
`managed` (el default): `makemigrations` genera DDL real y `migrate` lo aplica.
Alembic quedo congelado en la revision 143 -- ver apps/README.md.
"""

from django.db import models
from django.utils import timezone

from apps.plataforma.models import Timer

class RegistroConexion(Timer):
    id = models.BigAutoField(primary_key=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="registro_conexion")
    numero_expediente = models.CharField(max_length=100, null=True, blank=True)
    id_requerimiento_or = models.CharField(max_length=100, null=True, blank=True)
    numero_solicitud_appweb = models.CharField(max_length=100, null=True, blank=True)
    fecha_conexion_estimada = models.DateField(null=True, blank=True)
    vigencia_aprobacion_conexion = models.DateField(null=True, blank=True)
    fecha_visita_protecciones = models.DateField(null=True, blank=True)
    tipo_visita_protecciones = models.CharField(max_length=20, null=True, blank=True)
    exporta = models.BooleanField(default=False)
    comercializador_es_or = models.BooleanField(default=False)
    punto_conexion_texto = models.CharField(max_length=500, null=True, blank=True)
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "registro_conexion"


class RegistroEtapa(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="etapas")
    etapa = models.CharField(max_length=50)
    estado_actual = models.CharField(max_length=50)
    fecha_estado = models.DateTimeField(default=timezone.now)
    bloqueada = models.BooleanField(default=False)
    causa_bloqueo = models.CharField(max_length=500, null=True, blank=True)
    responsable_actual = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "registro_etapa"
        unique_together = [("etapa", "registro")]


class RegistroTransicion(models.Model):
    id = models.BigAutoField(primary_key=True)
    etapa = models.ForeignKey("RegistroEtapa", on_delete=models.CASCADE, db_column="etapa_id", related_name="transiciones")
    de_estado = models.CharField(max_length=50, null=True, blank=True)
    a_estado = models.CharField(max_length=50)
    fecha = models.DateTimeField(default=timezone.now)
    actor = models.CharField(max_length=30, null=True, blank=True)
    nota = models.CharField(max_length=1000, null=True, blank=True)
    evidencia_documento = models.ForeignKey("RegistroDocumento", on_delete=models.SET_NULL, db_column="evidencia_documento_id", null=True, blank=True, related_name="registro_transicion_por_evidencia_documento_id")

    class Meta:
        db_table = "registro_transicion"


class RegistroHito(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="hitos")
    hito = models.CharField(max_length=10)
    peso_pct = models.FloatField()
    completado = models.BooleanField(default=False)
    fecha_completado = models.DateTimeField(null=True, blank=True)
    evidencia_documento = models.ForeignKey("RegistroDocumento", on_delete=models.SET_NULL, db_column="evidencia_documento_id", null=True, blank=True, related_name="registro_hito_por_evidencia_documento_id")

    class Meta:
        db_table = "registro_hito"
        unique_together = [("hito", "registro")]


class RegistroParametros93(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="parametros_93")
    numero_unidades_equivalentes = models.IntegerField(null=True, blank=True)
    potencia_nominal_inversor_ac_mw = models.FloatField(null=True, blank=True)
    minimo_tecnico_mw = models.FloatField(null=True, blank=True)
    arranque_autonomo = models.BooleanField(default=False)
    acuerdo_conexion_compartida = models.BooleanField(default=False)
    voltaje_max_kv = models.FloatField(null=True, blank=True)
    voltaje_nominal_kv = models.FloatField(null=True, blank=True)
    voltaje_min_kv = models.FloatField(null=True, blank=True)
    frecuencia_max_hz = models.FloatField(null=True, blank=True, default=63)
    frecuencia_min_hz = models.FloatField(null=True, blank=True, default=57)
    impedancia_equivalente_ohm = models.FloatField(null=True, blank=True)
    icc_subtrans_pico_kap = models.FloatField(null=True, blank=True)
    icc_subtrans_3f_ka = models.FloatField(null=True, blank=True)
    icc_subtrans_2f_ka = models.FloatField(null=True, blank=True)
    icc_subtrans_1f_ka = models.FloatField(null=True, blank=True)
    icc_estado_estable_ka = models.FloatField(null=True, blank=True)
    in_eq_ka = models.FloatField(null=True, blank=True)
    coef_derrateo_altura = models.CharField(max_length=120, null=True, blank=True)
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "registro_parametros_93"


class RegistroEquipoFrontera(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="equipos")
    tipo = models.CharField(max_length=30)
    marca = models.CharField(max_length=120, null=True, blank=True)
    modelo = models.CharField(max_length=120, null=True, blank=True)
    serial = models.CharField(max_length=120, null=True, blank=True)
    fecha_solicitud_solenium = models.DateField(null=True, blank=True)
    fecha_envio_quoia = models.DateField(null=True, blank=True)
    fecha_parametrizacion = models.DateField(null=True, blank=True)
    fecha_envio_or = models.DateField(null=True, blank=True)
    fecha_vencimiento_calibracion = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "registro_equipo_frontera"


class RegistroDocumento(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="documentos")
    tipo = models.CharField(max_length=40)
    radicado = models.CharField(max_length=120, null=True, blank=True)
    fecha_emision = models.DateField(null=True, blank=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    firmado_por = models.CharField(max_length=200, null=True, blank=True)
    url_drive = models.CharField(max_length=1000, null=True, blank=True)
    estado = models.CharField(max_length=20, default="BORRADOR")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "registro_documento"


class RegistroAlerta(models.Model):
    id = models.BigAutoField(primary_key=True)
    registro = models.ForeignKey("RegistroConexion", on_delete=models.CASCADE, db_column="registro_id", related_name="alertas")
    tipo = models.CharField(max_length=40)
    fecha_disparo = models.DateTimeField()
    estado = models.CharField(max_length=20, default="PENDIENTE")
    mensaje = models.TextField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "registro_alerta"
        unique_together = [("dedupe_key",)]
