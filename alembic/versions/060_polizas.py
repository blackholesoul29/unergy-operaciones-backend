"""Crear tabla polizas (1 fila por proyecto)

Revision ID: 060
Revises: 059
Create Date: 2026-08-11
"""
from alembic import op
from alembic_idempotencia import verificar_columnas

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("""
        CREATE TABLE IF NOT EXISTS polizas (
            id                        BIGSERIAL PRIMARY KEY,
            proyecto_id               BIGINT NOT NULL UNIQUE REFERENCES proyectos(id),
            numero_poliza             VARCHAR(100),
            poliza_om                 BOOLEAN NOT NULL DEFAULT false,
            fecha_vencimiento         DATE,
            valor_poliza              NUMERIC(14,2),
            mano_obra                 NUMERIC(14,2),
            estructura                NUMERIC(14,2),
            paneles                   NUMERIC(14,2),
            inversores                NUMERIC(14,2),
            otros                     NUMERIC(14,2),
            valor_total_proyecto      NUMERIC(14,2),
            link_estudio_suelos       VARCHAR(500),
            ipp_base                  NUMERIC(10,4),
            ipp_base_fecha            DATE,
            ipp_provisional           NUMERIC(10,4),
            ipp_provisional_fecha     DATE,
            tarifa_base               NUMERIC(14,4),
            generacion_anual_p90_kwh  NUMERIC(14,2),
            valor_lucro_cesante       NUMERIC(14,2),
            created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at                TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_polizas_proyecto_id ON polizas(proyecto_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_polizas_fecha_vencimiento ON polizas(fecha_vencimiento)")
    verificar_columnas(bind, "polizas", {
        "id", "proyecto_id", "numero_poliza", "poliza_om", "fecha_vencimiento",
        "valor_poliza", "mano_obra", "estructura", "paneles", "inversores", "otros",
        "valor_total_proyecto", "link_estudio_suelos", "ipp_base", "ipp_base_fecha",
        "ipp_provisional", "ipp_provisional_fecha", "tarifa_base",
        "generacion_anual_p90_kwh", "valor_lucro_cesante", "created_at",
        "updated_at", "deleted_at",
    }, migracion="060")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS polizas")
