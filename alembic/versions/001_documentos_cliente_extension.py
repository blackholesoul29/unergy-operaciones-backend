"""Extensión documentos cliente: nuevos tipos enum, servicio_id y archivo_nombre

Revision ID: 001_docs_cliente
Revises:
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = "001_docs_cliente"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Usar IF NOT EXISTS en todo para que sea seguro correr incluso si init_db.py
    # ya creó las tablas con el modelo actualizado.

    # 1. Nuevos valores del enum — only if the type exists (fresh deploys
    #    create the table with the full enum via SQLAlchemy models, so the
    #    standalone type may not exist).
    op.execute("""
        DO $$ BEGIN
            ALTER TYPE tipodocumentoclienteenum ADD VALUE IF NOT EXISTS 'rut';
        EXCEPTION WHEN undefined_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TYPE tipodocumentoclienteenum ADD VALUE IF NOT EXISTS 'certificado_bancario';
        EXCEPTION WHEN undefined_object THEN NULL; END $$
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TYPE tipodocumentoclienteenum ADD VALUE IF NOT EXISTS 'camara_comercio';
        EXCEPTION WHEN undefined_object THEN NULL; END $$
    """)

    # 2. Columna archivo_nombre
    op.execute("""
        ALTER TABLE cliente_documentos_comerciales
        ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)
    """)

    # 3. Columna servicio_id
    op.execute("""
        ALTER TABLE cliente_documentos_comerciales
        ADD COLUMN IF NOT EXISTS servicio_id BIGINT
            REFERENCES cliente_servicios(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.drop_constraint("fk_doc_comercial_servicio", "cliente_documentos_comerciales", type_="foreignkey")
    op.drop_column("cliente_documentos_comerciales", "servicio_id")
    op.drop_column("cliente_documentos_comerciales", "archivo_nombre")
    # No se puede quitar valores de un enum en PostgreSQL sin recrearlo.
    # Si necesitas downgrade completo, debes recrear el tipo manualmente.
