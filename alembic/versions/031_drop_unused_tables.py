"""Elimina tablas huérfanas/vestigiales sin uso real en el código (confirmadas en 0 filas):
reglas_contables, rec_certificados, gmail_credenciales, equipos, equipos_sellos,
documentos, servicio_cgm, representacion_gescon, operacion_kpis, contratos_arriendo.

Los modelos SQLAlchemy correspondientes ya se quitaron del código (app/models/*),
así que Base.metadata.create_all() ya no las recrea al arrancar la app.

Revision ID: 031
Revises: 030
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Orden respetando FKs: primero las tablas hijas, luego las padres.
    op.drop_table("equipos_sellos")
    op.drop_table("equipos")
    op.drop_table("rec_certificados")
    op.drop_table("representacion_gescon")
    op.drop_table("operacion_kpis")
    op.drop_table("servicio_cgm")
    op.drop_table("contratos_arriendo")
    op.drop_table("documentos")
    op.drop_table("gmail_credenciales")
    op.drop_table("reglas_contables")

    # Tipos ENUM de Postgres que quedan huérfanos al borrar sus únicas tablas.
    sa.Enum(name="tipo_equipo_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="estado_certificado_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="estado_arriendo_enum").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.create_table(
        "reglas_contables",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre_proceso", sa.String(255), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("cuenta_debito", sa.String(20), nullable=True),
        sa.Column("cuenta_credito", sa.String(20), nullable=True),
        sa.Column("estrategia_etiquetas", sa.String(100), nullable=True),
        sa.Column("filtro_inversionista", sa.String(255), nullable=True),
        sa.Column("filtro_documento_contable", sa.String(50), nullable=True),
        sa.Column("filtro_contrato", sa.String(100), nullable=True),
        sa.Column("filtro_concepto", sa.String(255), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "gmail_credenciales",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("cuenta", sa.String(255), nullable=False, unique=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_actualizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_sync_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="desconectado"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "documentos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("tipo_documento", sa.String(255), nullable=False),
        sa.Column("nombre_archivo", sa.String(500), nullable=False),
        sa.Column("ruta_almacenamiento", sa.String(1000), nullable=False),
        sa.Column("file_id_drive", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cargado_por", sa.String(255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documentos_entity", "documentos", ["entity_type", "entity_id"])

    op.create_table(
        "contratos_arriendo",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proyecto_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=False, index=True),
        sa.Column("propietario_nombre", sa.String(255), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("hectareas", sa.Numeric(8, 4), nullable=True),
        sa.Column("verificado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("estado", sa.Enum("vigente", "vencido", "terminado", "en_renovacion", name="estado_arriendo_enum"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "servicio_cgm",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proyecto_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=False, unique=True),
        sa.Column("nit_cgm", sa.String(20), nullable=True),
        sa.Column("nombre_cgm", sa.String(255), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("plataforma_captura", sa.String(255), nullable=True),
        sa.Column("frecuencia_reporte", sa.String(50), nullable=False, server_default="diaria"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "operacion_kpis",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proyecto_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=False, index=True),
        sa.Column("servicio_operacion_id", sa.BigInteger(), sa.ForeignKey("servicio_operacion.id"), nullable=True),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fin", sa.Date(), nullable=False),
        sa.Column("energia_generada_kwh", sa.Numeric(14, 3), nullable=True),
        sa.Column("energia_esperada_kwh", sa.Numeric(14, 3), nullable=True),
        sa.Column("performance_ratio_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("disponibilidad_pct", sa.Numeric(6, 3), nullable=True),
        sa.Column("horas_equivalentes", sa.Numeric(8, 3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_operacion_kpis_servicio_id", "operacion_kpis", ["servicio_operacion_id"])

    op.create_table(
        "representacion_gescon",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proyecto_id", sa.BigInteger(), sa.ForeignKey("proyectos.id"), nullable=False, index=True),
        sa.Column("servicio_representacion_id", sa.BigInteger(), sa.ForeignKey("servicio_representacion.id"), nullable=True),
        sa.Column("codigo_contrato_gescon", sa.String(100), nullable=True),
        sa.Column("fecha_inicio", sa.Date(), nullable=True),
        sa.Column("fecha_fin", sa.Date(), nullable=True),
        sa.Column("cantidad_pactada_kwh", sa.Numeric(14, 3), nullable=True),
        sa.Column("codigos_sic", sa.String(500), nullable=True),
        sa.Column("precio_registrado", sa.Numeric(12, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_representacion_gescon_servicio_id", "representacion_gescon", ["servicio_representacion_id"])

    op.create_table(
        "equipos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("frontera_id", sa.BigInteger(), sa.ForeignKey("fronteras.id"), nullable=False, index=True),
        sa.Column("tipo_equipo", sa.Enum("medidor_principal", "medidor_respaldo", "ct", "pt", "bornera", name="tipo_equipo_enum"), nullable=False),
        sa.Column("marca", sa.String(255), nullable=True),
        sa.Column("modelo_referencia", sa.String(255), nullable=True),
        sa.Column("numero_serie", sa.String(100), nullable=True),
        sa.Column("clase_exactitud", sa.String(20), nullable=True),
        sa.Column("num_elementos", sa.Integer(), nullable=True),
        sa.Column("fecha_instalacion", sa.Date(), nullable=True),
        sa.Column("fecha_ultima_calibracion", sa.Date(), nullable=True),
        sa.Column("laboratorio_onac", sa.String(255), nullable=True),
        sa.Column("fecha_vencimiento_calibracion", sa.Date(), nullable=True),
        sa.Column("requiere_medidor_respaldo", sa.Boolean(), nullable=True),
        sa.Column("marca_modem", sa.String(255), nullable=True),
        sa.Column("modelo_modem", sa.String(255), nullable=True),
        sa.Column("protocolo_comunicacion", sa.String(100), nullable=True),
        sa.Column("apn_sim_operador", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "equipos_sellos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("equipo_id", sa.BigInteger(), sa.ForeignKey("equipos.id"), nullable=False, index=True),
        sa.Column("numero_sello", sa.String(100), nullable=False),
        sa.Column("fecha_instalacion", sa.Date(), nullable=False),
        sa.Column("persona_instalo", sa.String(255), nullable=True),
        sa.Column("retirado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fecha_retiro", sa.Date(), nullable=True),
        sa.Column("motivo_retiro", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "rec_certificados",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("proceso_id", sa.BigInteger(), sa.ForeignKey("rec_procesos.id"), nullable=False, unique=True, index=True),
        sa.Column("numero_certificado", sa.String(100), nullable=False),
        sa.Column("fecha_emision", sa.Date(), nullable=False),
        sa.Column("energia_certificada_mwh", sa.Numeric(14, 3), nullable=False),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fin", sa.Date(), nullable=False),
        sa.Column("titular_nombre", sa.String(255), nullable=False),
        sa.Column("titular_nit", sa.String(20), nullable=False),
        sa.Column("estado", sa.Enum("vigente", "transferido", "vencido", "anulado", name="estado_certificado_enum"), nullable=False, server_default="vigente"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
