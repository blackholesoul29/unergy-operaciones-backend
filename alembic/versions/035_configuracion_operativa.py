"""Configuración operativa: parámetros externalizados por proyecto o globales.

Tabla `configuracion_operativa` — externaliza valores antes hardcodeados en el
estimador de impacto de fallas (precio de energía de referencia COP/kWh y factor
de capacidad solar). `proyecto_id` NULL representa la configuración global; una
config específica de proyecto tiene prioridad sobre la global.

Se insertan como semilla los valores globales por defecto (los mismos de las
constantes originales) solo si no existen todavía.

IF NOT EXISTS / WHERE NOT EXISTS en cada paso para que reintentar la migración
desde cero sea seguro si un deploy se corta a medias (mismo criterio que
033_operadores_red y 034_maintenance_impact).

Revision ID: 035
Revises: 034
Create Date: 2026-07-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS configuracion_operativa (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT REFERENCES proyectos(id),
            tipo_parametro VARCHAR(50) NOT NULL
                CHECK (tipo_parametro IN ('PRECIO_ENERGIA', 'CAPACIDAD_SOLAR')),
            valor_float DOUBLE PRECISION NOT NULL,
            unidad VARCHAR(20) NOT NULL,
            fecha_inicio TIMESTAMPTZ NOT NULL DEFAULT now(),
            fecha_fin TIMESTAMPTZ,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            CONSTRAINT uq_config_proyecto_tipo_inicio
                UNIQUE (proyecto_id, tipo_parametro, fecha_inicio)
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_configuracion_operativa_proyecto_id "
        "ON configuracion_operativa (proyecto_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_configuracion_operativa_tipo_parametro "
        "ON configuracion_operativa (tipo_parametro)"
    ))

    # Semilla de configuración global por defecto (valores heredados de las
    # constantes originales de fallas.py). fecha_inicio fija para idempotencia.
    seeds = [
        ("PRECIO_ENERGIA", 800.0, "COP/kWh"),
        ("CAPACIDAD_SOLAR", 0.18, "factor"),
    ]
    for tipo, valor, unidad in seeds:
        conn.execute(
            sa.text("""
                INSERT INTO configuracion_operativa
                    (proyecto_id, tipo_parametro, valor_float, unidad, fecha_inicio, activo)
                SELECT NULL, :tipo, :valor, :unidad, TIMESTAMPTZ '2020-01-01 00:00:00+00', TRUE
                WHERE NOT EXISTS (
                    SELECT 1 FROM configuracion_operativa
                    WHERE proyecto_id IS NULL AND tipo_parametro = :tipo
                )
            """),
            {"tipo": tipo, "valor": valor, "unidad": unidad},
        )


def downgrade() -> None:
    op.drop_index("ix_configuracion_operativa_tipo_parametro", table_name="configuracion_operativa")
    op.drop_index("ix_configuracion_operativa_proyecto_id", table_name="configuracion_operativa")
    op.drop_table("configuracion_operativa")
