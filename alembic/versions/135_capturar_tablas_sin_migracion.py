"""Capturar en Alembic las 12 tablas que solo vivian en _PENDING_DDLS

Auditoria 2026-08-31: _PENDING_DDLS/init_db.py se retiraron el mismo dia
(commit 6ea67ae, "refactor(schema): drop _PENDING_DDLS and init_db for
Alembic-only") a favor de un esquema provisionado solo por Alembic, con
scripts/verificar_esquema.py como red de seguridad. Pero esa red de
seguridad solo compara contra Base.metadata.tables (lo que declaran los
modelos SQLAlchemy) -- y estas 12 tablas NUNCA tuvieron modelo ORM, eran
SQL crudo puro dentro de _PENDING_DDLS. Al retirar ese archivo sin
convertir sus CREATE TABLE a migraciones, ninguna de las 12 quedo
provisionada en ningun lado: ni por create_all() (sin modelo), ni por
Alembic (sin migracion), ni detectada por verificar_esquema.py (no
declarada). En la base de datos de produccion actual no pasa nada porque
ya existen fisicamente (las creo _PENDING_DDLS en su momento) -- el
problema es cualquier entorno nuevo desde cero (staging, recuperacion
ante desastre, un ambiente local), que quedaria silenciosamente sin
estas 12 tablas.

Todas se confirmaron en uso activo antes de escribir esta migracion (no
es una resurreccion automatica -- ver conversacion 2026-08-31):
  - alarma_estado, alarmas_monitoreo: alarmas de desconexion/monitoreo MGS
  - clima_oni_monthly/precip_monthly/price_monthly/forecasts: app/api/v1/evo_proxy.py
  - precios_bolsa_diario/horario: cumplimiento.py, dashboard.py, facturacion.py,
    contratos.py, services/simem_bolsa.py
  - audit_log: services/audit.py (auditoria de escrituras)
  - email_envios: services/email_service.py (log de todos los envios)
  - api_keys: api/v1/api_keys.py, auth.py (autenticacion por API key)
  - panel_consecutivo: api/v1/proyectos.py, models/panel_contable.py

email_envios incluye las columnas agregadas despues por otras entradas de
_PENDING_DDLS (proyectos, proyectos_total, cliente_id, operador_red_id,
proyecto_id) -- la migracion 120 ya asumia que cliente_id existia (solo
tocaba el ON DELETE de su FK), confirmando que esa columna nunca tuvo su
propio ADD COLUMN en Alembic tampoco. alarma_estado.categoria queda en
VARCHAR(40) (no el VARCHAR(20) original) por el mismo motivo -- se
ensancho despues, tambien solo en _PENDING_DDLS.

Todo con IF NOT EXISTS: no le hace nada a una base que ya las tiene.

Revision ID: 135
Revises: 134
Create Date: 2026-08-31
"""
from alembic import op

revision = "135"
down_revision = "134"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS alarma_estado (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL,
            categoria VARCHAR(40) NOT NULL,
            estado VARCHAR(30) NOT NULL,
            dia DATE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alarma_estado ON alarma_estado (proyecto_id, categoria)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS alarmas_monitoreo (
            id BIGSERIAL PRIMARY KEY,
            proyecto_nombre VARCHAR(255) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            alarm_type VARCHAR(50) NOT NULL,
            details TEXT NOT NULL,
            source_data JSONB,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_alarmas_monitoreo_created ON alarmas_monitoreo (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alarmas_monitoreo_severity ON alarmas_monitoreo (severity) WHERE resolved_at IS NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS clima_oni_monthly (
            id BIGSERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            oni_value REAL NOT NULL,
            soi_value REAL,
            pdo_value REAL,
            mjo_amplitude REAL,
            enso_phase VARCHAR(20),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(year, month)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS clima_precip_monthly (
            id BIGSERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            region VARCHAR(50) NOT NULL,
            precip_mm REAL NOT NULL,
            anomaly_pct REAL,
            climatology_mm REAL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(year, month, region)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS clima_price_monthly (
            id BIGSERIAL PRIMARY KEY,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            price_cop_kwh REAL NOT NULL,
            enso_phase VARCHAR(20),
            precip_andina_mm REAL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(year, month)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS clima_forecasts (
            id BIGSERIAL PRIMARY KEY,
            forecast_date DATE NOT NULL,
            forecast_json JSONB NOT NULL,
            model_version VARCHAR(50) DEFAULT 'v1_statistical',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_clima_oni_ym ON clima_oni_monthly (year, month)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_clima_precip_ym ON clima_precip_monthly (year, month, region)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_clima_price_ym ON clima_price_monthly (year, month)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_clima_forecasts_date ON clima_forecasts (forecast_date DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS precios_bolsa_diario (
            id BIGSERIAL PRIMARY KEY,
            fecha DATE NOT NULL,
            precio_promedio REAL NOT NULL,
            precio_min REAL,
            precio_max REAL,
            precio_escasez REAL,
            demanda_gwh REAL,
            hidro_pct REAL,
            termica_pct REAL,
            renovable_pct REAL,
            menor_pct REAL,
            hora_pico INTEGER,
            spread REAL,
            source_data JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(fecha)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS precios_bolsa_horario (
            id BIGSERIAL PRIMARY KEY,
            fecha DATE NOT NULL,
            hora INTEGER NOT NULL CHECK (hora BETWEEN 1 AND 24),
            precio_cop_kwh REAL NOT NULL,
            gen_hidro REAL,
            gen_termica REAL,
            gen_renovable REAL,
            gen_menor REAL,
            planta_marginal VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(fecha, hora)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_precios_bolsa_diario_fecha ON precios_bolsa_diario (fecha DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_precios_bolsa_horario_fecha ON precios_bolsa_horario (fecha DESC, hora)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            tabla VARCHAR(100) NOT NULL,
            registro_id BIGINT NOT NULL,
            accion VARCHAR(10) NOT NULL,
            usuario_id BIGINT,
            usuario_nombre VARCHAR(255),
            cambios JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_tabla_registro ON audit_log (tabla, registro_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_created ON audit_log (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_usuario ON audit_log (usuario_id) WHERE usuario_id IS NOT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS email_envios (
            id BIGSERIAL PRIMARY KEY,
            destinatario VARCHAR(500) NOT NULL,
            cc TEXT,
            asunto VARCHAR(500) NOT NULL,
            tipo VARCHAR(50) NOT NULL,
            exitoso BOOLEAN NOT NULL DEFAULT TRUE,
            error TEXT,
            enviado_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_envios_tipo ON email_envios (tipo)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_envios_at ON email_envios (enviado_at DESC)")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS proyectos TEXT")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS proyectos_total INTEGER")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS cliente_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS operador_red_id BIGINT REFERENCES operadores_red(id)")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS proyecto_id BIGINT REFERENCES proyectos(id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id BIGSERIAL PRIMARY KEY,
            usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            nombre VARCHAR(255) NOT NULL,
            key_hash VARCHAR(255) NOT NULL,
            key_prefix VARCHAR(12) NOT NULL,
            scopes JSONB NOT NULL DEFAULT '["read"]'::jsonb,
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            ultimo_uso TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_usuario ON api_keys (usuario_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON api_keys (key_prefix)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys (key_hash)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS panel_consecutivo (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            periodo VARCHAR(7) NOT NULL,
            tipo VARCHAR(20) NOT NULL,
            proyecto_inversionista_id BIGINT REFERENCES proyecto_inversionistas(id) ON DELETE SET NULL,
            inversionista_nombre VARCHAR(255) NOT NULL,
            consecutivo_ingresos INTEGER,
            consecutivo_costos INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_panel_consec_proy_per_tipo_inv
                UNIQUE (proyecto_id, periodo, tipo, inversionista_nombre)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_panel_consec_periodo_tipo ON panel_consecutivo (periodo, tipo)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_panel_consec_proyecto ON panel_consecutivo (proyecto_id)")


def downgrade():
    # No-op a propósito: estas tablas existían antes de esta migración (la
    # creó _PENDING_DDLS originalmente) y las usa código en producción --
    # bajar esta revisión no debe borrarlas.
    pass
