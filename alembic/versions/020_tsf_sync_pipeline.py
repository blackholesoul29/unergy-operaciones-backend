"""Pipeline TSF / próximos a energizarse — campos de sincronización en proyectos

Revision ID: 020
Revises: 020a
Create Date: 2026-06-15
"""
from alembic import op

revision = "020"
down_revision = "020a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Correlación con originabotdb.minifarm_project.name / base_name de Sun Factory.
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origina_code VARCHAR(100)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyectos_origina_code "
        "ON proyectos (origina_code) WHERE origina_code IS NOT NULL"
    )
    # Fase del pipeline de construcción (complementa `estado`).
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fase_construccion VARCHAR(40)")
    # Fecha tentativa de energización (de TSF la 1ª vez; editable por operaciones).
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_estimada_energizacion DATE")
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS "
        "fecha_estimada_editada_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS avance_obra_pct NUMERIC(5,2)")
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS mwh_mes_estimado NUMERIC(12,2)")
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origen VARCHAR(20) DEFAULT 'manual'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proyectos_origina_code")
    for col in (
        "origina_code",
        "fase_construccion",
        "fecha_estimada_energizacion",
        "fecha_estimada_editada_manual",
        "avance_obra_pct",
        "mwh_mes_estimado",
        "origen",
    ):
        op.execute(f"ALTER TABLE proyectos DROP COLUMN IF EXISTS {col}")
