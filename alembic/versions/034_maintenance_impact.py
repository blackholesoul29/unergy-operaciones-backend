"""Impacto de mantenimiento: downtime, energía perdida e impacto económico.

Tabla `mantenimiento_impacto` — registra los eventos de mantenimiento (programado
/ no programado) de una planta, la energía teórica esperada vs. la real, la
energía perdida derivada y su valoración en COP, además de una bandera de riesgo
de penalización PPA. El vínculo opcional a `fallas` permite generar el impacto a
partir de una falla que terminó en intervención.

IF NOT EXISTS en cada paso para que reintentar la migración desde cero sea seguro
si un deploy se corta a medias (mismo criterio que 033_operadores_red).

Revision ID: 034
Revises: 033
Create Date: 2026-07-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS mantenimiento_impacto (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            falla_id BIGINT REFERENCES fallas(id) ON DELETE SET NULL,
            maintenance_type VARCHAR(50) NOT NULL DEFAULT 'scheduled',
            start_time TIMESTAMPTZ NOT NULL,
            end_time TIMESTAMPTZ NOT NULL,
            expected_generation_kwh NUMERIC(12, 2),
            actual_generation_kwh NUMERIC(12, 2),
            lost_energy_kwh NUMERIC(12, 2),
            financial_impact_cop NUMERIC(15, 2),
            ppa_penalty_risk_flag BOOLEAN NOT NULL DEFAULT FALSE,
            created_by BIGINT REFERENCES usuarios(id),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_mantenimiento_impacto_proyecto_id "
        "ON mantenimiento_impacto (proyecto_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_mantenimiento_impacto_falla_id "
        "ON mantenimiento_impacto (falla_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_mantenimiento_impacto_start_time "
        "ON mantenimiento_impacto (start_time)"
    ))


def downgrade() -> None:
    op.drop_index("ix_mantenimiento_impacto_start_time", table_name="mantenimiento_impacto")
    op.drop_index("ix_mantenimiento_impacto_falla_id", table_name="mantenimiento_impacto")
    op.drop_index("ix_mantenimiento_impacto_proyecto_id", table_name="mantenimiento_impacto")
    op.drop_table("mantenimiento_impacto")
