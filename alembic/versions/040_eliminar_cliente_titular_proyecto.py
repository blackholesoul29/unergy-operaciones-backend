"""Eliminar proyectos.cliente_id (titular) -- sin dependencia funcional real.

Todo lo que antes leia el titular (contactos, reporte_cgm, fallas, portal de
monitoreo) ya migro a ProyectoInversionista. La migracion 038 garantizo que
todo proyecto con titular tambien tiene su fila de inversionista (100% si no
tenia ninguno), asi que no hace falta backfill adicional aqui -- solo
eliminar la columna y su indice.

Revision ID: 040
Revises: 039
Create Date: 2026-07-08
"""
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proyectos_cliente_id")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS cliente_id")


def downgrade() -> None:
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cliente_id BIGINT REFERENCES clientes(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proyectos_cliente_id ON proyectos (cliente_id)")
