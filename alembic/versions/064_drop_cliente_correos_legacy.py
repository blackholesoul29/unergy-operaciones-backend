"""Elimina los 6 campos de correo sueltos en clientes (superados por Contacto).

correo_liquidacion/correo_monitoreo/correo_soporte/correo_operacional/
correos_operacionales/correos_cgm quedaron huerfanos desde la migracion 037
(2026-07-07), que los reemplazo por la tabla `contactos` -- ningun codigo
del backend ni del frontend los lee ni los escribe desde entonces.

Por seguridad, antes de borrar se repite el MISMO backfill de la 037 hacia
`contactos` (ON CONFLICT DO NOTHING, no duplica nada ya migrado) -- asi
cualquier valor cargado despues de esa migracion tambien queda a salvo.

Revision ID: 064
Revises: 063
Create Date: 2026-08-19
"""
from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for columna, tipo in (
        ("correo_operacional", "operacional"),
        ("correo_liquidacion", "liquidacion"),
        ("correo_monitoreo", "monitoreo"),
        ("correo_soporte", "soporte"),
    ):
        op.execute(f"""
            INSERT INTO contactos (cliente_id, email, tipo)
            SELECT id, lower(trim({columna})), '{tipo}'
            FROM clientes
            WHERE {columna} IS NOT NULL AND trim({columna}) <> ''
            ON CONFLICT (cliente_id, email, tipo) DO NOTHING
        """)

    for columna, tipo in (
        ("correos_operacionales", "operacional"),
        ("correos_cgm", "cgm"),
    ):
        op.execute(f"""
            INSERT INTO contactos (cliente_id, email, tipo)
            SELECT c.id, lower(trim(e)), '{tipo}'
            FROM clientes c, jsonb_array_elements_text(COALESCE(c.{columna}, '[]'::jsonb)) AS e
            WHERE trim(e) <> ''
            ON CONFLICT (cliente_id, email, tipo) DO NOTHING
        """)

    for columna in (
        "correo_liquidacion", "correo_monitoreo", "correo_soporte",
        "correo_operacional", "correos_operacionales", "correos_cgm",
    ):
        op.execute(f"ALTER TABLE clientes DROP COLUMN IF EXISTS {columna}")


def downgrade() -> None:
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_liquidacion VARCHAR(255)")
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_monitoreo VARCHAR(255)")
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_soporte VARCHAR(255)")
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_operacional VARCHAR(255)")
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correos_operacionales JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correos_cgm JSONB DEFAULT '[]'::jsonb")
