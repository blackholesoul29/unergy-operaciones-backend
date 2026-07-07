"""Automatización de liquidación XM: tabla de ingesta + estado en informes.

- `liquidacion_xm_ingesta`: salida del proceso que, al aprobar un informe,
  correlaciona la generación diaria del proyecto con el precio de bolsa del MEM
  (energía * precio = valor liquidado). Es distinta de `liquidacion_xm_datos`
  (líneas curadas de una Liquidacion manual).
- `informes_guardados.liquidacion_status`: estado de esa automatización
  (PENDIENTE | EN_PROCESO | COMPLETADO | ERROR).

IF NOT EXISTS en cada paso para que reintentar desde cero sea seguro si un deploy
se corta a medias (mismo criterio que 034_maintenance_impact).

Revision ID: 20260615
Revises: 038
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260615"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "ALTER TABLE informes_guardados "
        "ADD COLUMN IF NOT EXISTS liquidacion_status VARCHAR(20) "
        "NOT NULL DEFAULT 'PENDIENTE'"
    ))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS liquidacion_xm_ingesta (
            id BIGSERIAL PRIMARY KEY,
            informe_id BIGINT NOT NULL REFERENCES informes_guardados(id) ON DELETE CASCADE,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            ppa_contrato_id BIGINT REFERENCES ppa_contratos(id) ON DELETE SET NULL,
            fecha DATE NOT NULL,
            hora INTEGER,
            energia_generada_kwh NUMERIC(15, 4) NOT NULL,
            precio_bolsa_cop_kwh NUMERIC(15, 4),
            valor_liquidado_cop NUMERIC(18, 4),
            fuente_datos VARCHAR(50) NOT NULL,
            estado_proceso VARCHAR(20) NOT NULL DEFAULT 'procesado',
            datos_adicionales JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_liq_xm_ingesta_hora CHECK (hora IS NULL OR (hora >= 0 AND hora <= 23)),
            CONSTRAINT uq_liq_xm_ingesta_informe_proyecto_fecha_hora
                UNIQUE (informe_id, proyecto_id, fecha, hora)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_liq_xm_ingesta_informe_id "
        "ON liquidacion_xm_ingesta (informe_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_liq_xm_ingesta_proyecto_fecha "
        "ON liquidacion_xm_ingesta (proyecto_id, fecha)"
    ))


def downgrade() -> None:
    op.drop_index("ix_liq_xm_ingesta_proyecto_fecha", table_name="liquidacion_xm_ingesta")
    op.drop_index("ix_liq_xm_ingesta_informe_id", table_name="liquidacion_xm_ingesta")
    op.drop_table("liquidacion_xm_ingesta")
    op.execute("ALTER TABLE informes_guardados DROP COLUMN IF EXISTS liquidacion_status")
