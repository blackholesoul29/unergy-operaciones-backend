"""Modelos del dominio `comercial`.

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

class Oportunidad(Timer):
    id = models.BigAutoField(primary_key=True)
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.DO_NOTHING, db_column="cliente_id", related_name="oportunidades_por_cliente_id")
    nombre = models.CharField(max_length=255, null=True, blank=True)
    estado = models.CharField(max_length=11, choices=[("oportunidad", "oportunidad"), ("oferta", "oferta"), ("contrato", "contrato"), ("firmado", "firmado"), ("operando", "operando"), ("terminado", "terminado"), ("declinado", "declinado")], default="oportunidad")
    estado_desde = models.DateTimeField(default=timezone.now)
    numero_oferta = models.CharField(max_length=100, null=True, blank=True)
    fecha_tentativa_inicio_representacion = models.DateField(null=True, blank=True)
    fecha_tentativa_inicio_compra_energia = models.DateField(null=True, blank=True)
    fecha_estimada_firma = models.DateField(null=True, blank=True)
    notas = models.TextField(null=True, blank=True)
    es_migrada = models.BooleanField(default=False)
    creado_por_usuario = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="creado_por_usuario_id", null=True, blank=True, related_name="oportunidades_por_creado_por_usuario_id")
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "oportunidades"


class OportunidadEstadoHistorial(models.Model):
    id = models.BigAutoField(primary_key=True)
    oportunidad = models.ForeignKey("Oportunidad", on_delete=models.DO_NOTHING, db_column="oportunidad_id", related_name="oportunidad_estado_historial_por_oportunidad_id")
    oferta = models.ForeignKey("OportunidadOferta", on_delete=models.CASCADE, db_column="oferta_id", null=True, blank=True, related_name="oportunidad_estado_historial_por_oferta_id")
    estado_anterior = models.CharField(max_length=20, null=True, blank=True)
    estado_nuevo = models.CharField(max_length=20)
    usuario = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="usuario_id", null=True, blank=True, related_name="oportunidad_estado_historial_por_usuario_id")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "oportunidad_estado_historial"


class OportunidadGestion(models.Model):
    id = models.BigAutoField(primary_key=True)
    oportunidad = models.ForeignKey("Oportunidad", on_delete=models.DO_NOTHING, db_column="oportunidad_id", related_name="gestiones")
    oferta = models.ForeignKey("OportunidadOferta", on_delete=models.SET_NULL, db_column="oferta_id", null=True, blank=True, related_name="oportunidad_gestiones_por_oferta_id")
    tipo = models.CharField(max_length=8, choices=[("llamada", "llamada"), ("correo", "correo"), ("reunion", "reunion"), ("whatsapp", "whatsapp"), ("nota", "nota")])
    descripcion = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey("plataforma.Usuario", on_delete=models.DO_NOTHING, db_column="usuario_id", null=True, blank=True, related_name="oportunidad_gestiones_por_usuario_id")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "oportunidad_gestiones"


class OportunidadOferta(Timer):
    id = models.BigAutoField(primary_key=True)
    oportunidad = models.ForeignKey("Oportunidad", on_delete=models.DO_NOTHING, db_column="oportunidad_id", related_name="ofertas")
    tipo = models.CharField(max_length=23, choices=[("servicios_operacionales", "servicios_operacionales"), ("compra_energia", "compra_energia"), ("comunidad_energetica", "comunidad_energetica")])
    planta_nombre = models.CharField(max_length=255, null=True, blank=True)
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.DO_NOTHING, db_column="proyecto_id", null=True, blank=True, related_name="oportunidad_ofertas_por_proyecto_id")
    numero_oferta = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    precio_detalle = models.TextField(null=True, blank=True)
    estado = models.CharField(max_length=11, choices=[("oportunidad", "oportunidad"), ("oferta", "oferta"), ("contrato", "contrato"), ("firmado", "firmado"), ("operando", "operando"), ("terminado", "terminado"), ("declinado", "declinado")], default="oportunidad")
    estado_desde = models.DateTimeField(default=timezone.now)
    resultado = models.CharField(max_length=9, choices=[("pendiente", "pendiente"), ("aceptado", "aceptado"), ("declinado", "declinado")], default="pendiente")
    etapa_texto = models.CharField(max_length=60, null=True, blank=True)
    fecha_oferta = models.DateField(null=True, blank=True)
    fecha_tentativa_inicio = models.DateField(null=True, blank=True)
    fecha_fin_tentativa = models.DateField(null=True, blank=True)
    contrato_firmado = models.CharField(max_length=150, null=True, blank=True)
    detalle = models.JSONField(null=True, blank=True)
    seguimientos = models.IntegerField(default=0)
    fecha_ultima_respuesta = models.DateField(null=True, blank=True)
    documento_url = models.CharField(max_length=1000, null=True, blank=True)
    ppa_contrato = models.ForeignKey("ppa.PpaContrato", on_delete=models.SET_NULL, db_column="ppa_contrato_id", null=True, blank=True, related_name="oportunidad_ofertas_por_ppa_contrato_id")
    contrato_servicio = models.ForeignKey("contratos.ContratoServicio", on_delete=models.SET_NULL, db_column="contrato_servicio_id", null=True, blank=True, related_name="oportunidad_ofertas_por_contrato_servicio_id")
    municipio = models.CharField(max_length=100, null=True, blank=True)
    departamento = models.CharField(max_length=100, null=True, blank=True)
    operador_red = models.ForeignKey("fronteras.OperadorRed", on_delete=models.DO_NOTHING, db_column="operador_red_id", null=True, blank=True, related_name="oportunidad_ofertas_por_operador_red_id")
    energia_promedio_kwh_mes = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    notas = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "oportunidad_ofertas"


class OportunidadOfertaProyecto(models.Model):
    oferta = models.ForeignKey("OportunidadOferta", on_delete=models.CASCADE, db_column="oferta_id", related_name="proyectos_declarados")
    proyecto = models.ForeignKey("proyectos.Proyecto", on_delete=models.CASCADE, db_column="proyecto_id", related_name="oportunidad_oferta_proyectos_por_proyecto_id")
    pk = models.CompositePrimaryKey("oferta_id", "proyecto_id")

    class Meta:
        db_table = "oportunidad_oferta_proyectos"
