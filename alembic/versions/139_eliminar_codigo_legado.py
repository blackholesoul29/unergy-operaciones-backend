"""Eliminar fallas.codigo_legado

Auditoria del dominio Fallas 2026-09-02: `codigo_legado` (agregada en la
migracion 002) nacio como llave de idempotencia de una migracion puntual
de fallas desde un Google Apps Script (`migrate_fallas_desde_sheets.py`,
ahora eliminado del repo -- ya cumplio su proposito, 1082 fallas migradas
en 2026-04). Se reconvirtio despues en llave de idempotencia general para
la API publica (docs/API_FALLAS.md), pero sin evidencia de trafico externo
activo hoy (la unica huella real encontrada, ~5000 filas con un patron
LAURA-{hash}-{numero}, esta concentrada en una franja de horas del
2026-08-20 -- una corrida puntual, no trafico continuo). Decision de
negocio: eliminar el campo.

codigo_interno (el codigo FAL-{año}-{id}, autogenerado por el servidor)
NO reemplaza esta funcion -- no puede servir como llave de idempotencia
porque no existe hasta DESPUES de crear la fila; el cliente no puede
mandarlo de antemano para detectar un reintento.

Se pierde el dato historico de con qué código del sistema anterior se
correspondía cada falla migrada (~6000 filas en produccion a la fecha de
esta migracion tenian codigo_legado poblado) -- se acepta la perdida,
decision de negocio 2026-09-02.

Revision ID: 139
Revises: 138
Create Date: 2026-09-02
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "139"
down_revision = "138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not columna_existe(bind, "fallas", "codigo_legado"):
        return
    # DROP COLUMN se lleva consigo el indice y la unique constraint que
    # vivian sobre ella (ix_fallas_codigo_legado, uq_fallas_codigo_legado).
    op.drop_column("fallas", "codigo_legado")


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    if columna_existe(bind, "fallas", "codigo_legado"):
        return
    op.add_column("fallas", sa.Column("codigo_legado", sa.String(30), nullable=True))
    op.create_unique_constraint("uq_fallas_codigo_legado", "fallas", ["codigo_legado"])
    op.create_index("ix_fallas_codigo_legado", "fallas", ["codigo_legado"])
