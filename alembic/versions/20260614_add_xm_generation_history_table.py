"""Crear tabla xm_generation_history (histórico de generación XM / SinergoX)

Revision ID: 026
Revises: 025
Create Date: 2026-06-14
"""
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # generation_kwh: kWh es la unidad canónica del repo para generación cruda
    # (ver app/schemas/generacion.py kwh_real/kwh_p90 y fronteras.energia_activa_*_kwh).
    # El servicio de ingesta convierte ×1000 cuando el Excel viene en MWh, evitando una
    # inflación 1000× en liquidación/PPA.
    op.execute("""
        CREATE TABLE IF NOT EXISTS xm_generation_history (
            id                BIGSERIAL PRIMARY KEY,
            proyecto_id       BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            meter_id          VARCHAR(100) NOT NULL,
            measurement_date  TIMESTAMP NOT NULL,
            generation_kwh    NUMERIC(18, 6) NOT NULL,
            source_file       VARCHAR(255),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_xm_gen_hist_proj_date_meter
                UNIQUE (proyecto_id, measurement_date, meter_id)
        )
    """)
    # Defensa idempotente: si una versión previa de esta tabla quedó creada con la
    # columna mal nombrada `generation_mwh`, renómbrala (sin tocar los valores, que
    # ya estaban en kWh por la convención del repo) en vez de duplicar columnas.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'xm_generation_history'
                         AND column_name = 'generation_mwh')
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = 'xm_generation_history'
                         AND column_name = 'generation_kwh') THEN
                ALTER TABLE xm_generation_history
                    RENAME COLUMN generation_mwh TO generation_kwh;
            END IF;
        END $$;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_xm_gen_hist_proj_date "
        "ON xm_generation_history (proyecto_id, measurement_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS xm_generation_history")
