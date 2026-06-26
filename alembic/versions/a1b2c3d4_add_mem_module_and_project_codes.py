"""Add MEM module and project codes

Crea las tablas del módulo MEM (generación ASIC, precios de bolsa, estados
GESCON y pre-liquidaciones) y agrega los identificadores XM (codigo_asic /
codigo_cno) a la tabla proyectos.

NOTA: en producción el esquema se materializa vía create_all + _PENDING_DDLS al
arrancar (app/main.py). Esta migración replica esos cambios para entornos que
usen Alembic. Todo el DDL es idempotente.

Revision ID: a1b2c3d4
Revises: 030
Create Date: 2026-06-25
"""
from alembic import op

revision = "a1b2c3d4"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── proyectos: identificadores XM ──────────────────────────────────────
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS codigo_asic VARCHAR(50)")
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS codigo_cno VARCHAR(50)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_proyectos_codigo_asic ON proyectos (codigo_asic)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_proyectos_codigo_cno ON proyectos (codigo_cno)")

    # ── mem_datos_asic ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mem_datos_asic (
            id              BIGSERIAL PRIMARY KEY,
            proyecto_id     BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            fecha           DATE NOT NULL,
            hora            INTEGER NOT NULL,
            generacion_kwh  DOUBLE PRECISION NOT NULL,
            fuente          VARCHAR(100),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_mem_asic_hora CHECK (hora >= 0 AND hora <= 23),
            CONSTRAINT uq_mem_asic_proyecto_fecha_hora UNIQUE (proyecto_id, fecha, hora)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mem_datos_asic_proyecto_id ON mem_datos_asic (proyecto_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mem_datos_asic_fecha ON mem_datos_asic (fecha)")

    # ── mem_precios_bolsa ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mem_precios_bolsa (
            id              BIGSERIAL PRIMARY KEY,
            fecha           DATE NOT NULL,
            hora            INTEGER NOT NULL,
            precio_cop_kwh  DOUBLE PRECISION NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_mem_precio_hora CHECK (hora >= 0 AND hora <= 23),
            CONSTRAINT uq_mem_precio_fecha_hora UNIQUE (fecha, hora)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mem_precios_bolsa_fecha ON mem_precios_bolsa (fecha)")

    # ── mem_gescon_estados ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mem_gescon_estados (
            id                  BIGSERIAL PRIMARY KEY,
            proyecto_id         BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            estado              VARCHAR(100) NOT NULL,
            fecha_actualizacion TIMESTAMPTZ NOT NULL,
            observaciones       TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mem_gescon_estados_proyecto_id ON mem_gescon_estados (proyecto_id)")

    # ── liquidaciones_preliminares ─────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE estado_liquidacion_preliminar_enum AS ENUM
                ('pendiente_revision', 'aprobada', 'rechazada');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS liquidaciones_preliminares (
            id                BIGSERIAL PRIMARY KEY,
            liquidacion_id    BIGINT REFERENCES liquidaciones(id) ON DELETE SET NULL,
            proyecto_id       BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            periodo           DATE NOT NULL,
            estado            estado_liquidacion_preliminar_enum NOT NULL DEFAULT 'pendiente_revision',
            datos_calculados  JSONB,
            invoice_generated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_liq_preliminar_proyecto_periodo UNIQUE (proyecto_id, periodo)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_liq_preliminares_proyecto_id ON liquidaciones_preliminares (proyecto_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_liq_preliminares_liquidacion_id ON liquidaciones_preliminares (liquidacion_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS liquidaciones_preliminares")
    op.execute("DROP TYPE IF EXISTS estado_liquidacion_preliminar_enum")
    op.execute("DROP TABLE IF EXISTS mem_gescon_estados")
    op.execute("DROP TABLE IF EXISTS mem_precios_bolsa")
    op.execute("DROP TABLE IF EXISTS mem_datos_asic")
    op.execute("DROP INDEX IF EXISTS ix_proyectos_codigo_cno")
    op.execute("DROP INDEX IF EXISTS ix_proyectos_codigo_asic")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS codigo_cno")
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS codigo_asic")
