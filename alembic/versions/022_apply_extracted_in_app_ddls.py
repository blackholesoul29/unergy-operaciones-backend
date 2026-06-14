"""Apply extracted in-app DDLs

Migra a Alembic todas las sentencias DDL idempotentes que antes se ejecutaban
en el arranque de la app (``_PENDING_DDLS`` en ``app/main.py``) y en
``init_db.add_columns()``. Incluye objetos que NO existen como modelos
SQLAlchemy (p.ej. ``audit_log``, ``alarma_estado``, ``alarmas_monitoreo``,
índices de rendimiento, fixes de datos), por lo que es imprescindible para
construir el esquema completo en una BD nueva — ``create_all`` (migración 021)
no los crea.

Comportamiento fiel al original:
- Cada sentencia se ejecuta de forma tolerante a fallos (igual que el viejo
  ``_run_column_migrations`` / ``add_columns`` envueltos en try/except). Esto
  preserva la idempotencia: re-ejecutar la migración sobre una BD que ya tiene
  los objetos no falla.
- ``ALTER TYPE … ADD VALUE`` debe correr fuera de un bloque de transacción en
  PostgreSQL; se ejecuta primero en conexiones AUTOCOMMIT separadas, de modo
  que los nuevos valores enum existen antes del DDL regular que los referencia.

Revision ID: 022
Revises: 021
Create Date: 2026-06-14
"""
from alembic import op
from sqlalchemy import text

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


# ── DDLs extraídos de app/main.py (_PENDING_DDLS) ───────────────────────────────
_PENDING_DDLS = [
    # alarmas de desconexión — estado por proyecto (anti-spam + re-aviso diario)
    """CREATE TABLE IF NOT EXISTS alarma_estado (
        id BIGSERIAL PRIMARY KEY,
        proyecto_id BIGINT NOT NULL,
        categoria VARCHAR(20) NOT NULL,
        estado VARCHAR(30) NOT NULL,
        dia DATE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_alarma_estado ON alarma_estado (proyecto_id, categoria)",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS codigo_legado VARCHAR(30)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_fallas_codigo_legado_unique ON fallas (codigo_legado) WHERE codigo_legado IS NOT NULL",
    # migration 003 — monitoreo fields
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS fotos_urls JSONB",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS centinela VARCHAR(200)",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS notificacion BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS alias_monitoreo TEXT",
    """CREATE TABLE IF NOT EXISTS generacion_diaria (
        id BIGSERIAL PRIMARY KEY,
        proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
        fecha DATE NOT NULL,
        kwh_real NUMERIC(14,3),
        kwh_p90 NUMERIC(14,3),
        kwh_autoconsumo NUMERIC(14,3),
        fuente VARCHAR(50) NOT NULL DEFAULT 'manual',
        notas TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_generacion_proyecto_fecha ON generacion_diaria (proyecto_id, fecha)",
    "CREATE INDEX IF NOT EXISTS ix_generacion_proyecto_fecha ON generacion_diaria (proyecto_id, fecha)",
    "CREATE INDEX IF NOT EXISTS ix_generacion_fecha ON generacion_diaria (fecha)",
    """CREATE TABLE IF NOT EXISTS monitoreo_verificaciones (
        id BIGSERIAL PRIMARY KEY,
        email VARCHAR(255) NOT NULL,
        codigo VARCHAR(6) NOT NULL,
        usado BOOLEAN NOT NULL DEFAULT FALSE,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_monitoreo_ver_email ON monitoreo_verificaciones (email)",
    # migration 004 — P50/P90 monthly simulation per project (JSON arrays of 12 values)
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS p90_mensual_kwh JSONB",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS p50_mensual_kwh JSONB",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS p99_mensual_kwh JSONB",
    # migration 005 — código TSF (frontera CREG) por proyecto
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS codigo_tsf VARCHAR(100)",
    # migration 006 — múltiples correos por cliente (T14)
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_liquidacion VARCHAR(255)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_monitoreo VARCHAR(255)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_soporte VARCHAR(255)",
    # migration 007 — tabla de gestión de proyectos (T16)
    """CREATE TABLE IF NOT EXISTS gestion_registros (
        id BIGSERIAL PRIMARY KEY,
        proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
        tipo VARCHAR(50) NOT NULL,
        titulo VARCHAR(500) NOT NULL,
        descripcion TEXT,
        archivos_json JSONB,
        created_by VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_gestion_proyecto ON gestion_registros (proyecto_id)",
    "CREATE INDEX IF NOT EXISTS ix_gestion_tipo ON gestion_registros (tipo)",
    # migration 008 — columnas faltantes en proyecto_inversionistas
    "ALTER TABLE proyecto_inversionistas ADD COLUMN IF NOT EXISTS contrato_ref VARCHAR(100)",
    "ALTER TABLE proyecto_inversionistas ADD COLUMN IF NOT EXISTS fecha_inicio DATE",
    "ALTER TABLE proyecto_inversionistas ADD COLUMN IF NOT EXISTS fecha_fin DATE",
    "ALTER TABLE proyecto_inversionistas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    # migration 009 — tablas de servicios y documentos de clientes
    # CREATE TYPE falla si ya existe → excepción capturada y saltada, sin problema
    "CREATE TYPE tipo_servicio_cliente_enum AS ENUM ('operacion', 'representacion', 'cgm', 'promotor')",
    "CREATE TYPE tipo_documento_cliente_enum AS ENUM ('oferta', 'contrato')",
    "CREATE TYPE estado_documento_cliente_enum AS ENUM ('borrador', 'enviado', 'aceptado', 'firmado', 'rechazado')",
    """CREATE TABLE IF NOT EXISTS cliente_servicios (
        id BIGSERIAL PRIMARY KEY,
        cliente_id BIGINT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
        tipo tipo_servicio_cliente_enum NOT NULL,
        fecha_inicio DATE,
        notas TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS cliente_documentos_comerciales (
        id BIGSERIAL PRIMARY KEY,
        cliente_id BIGINT NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
        tipo tipo_documento_cliente_enum NOT NULL,
        nombre VARCHAR(255) NOT NULL,
        numero VARCHAR(100),
        fecha DATE,
        estado estado_documento_cliente_enum NOT NULL DEFAULT 'borrador',
        archivo_url VARCHAR(1000),
        notas TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS rut_url VARCHAR(1000)",
    "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)",
    "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS servicio_id BIGINT REFERENCES cliente_servicios(id) ON DELETE SET NULL",
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'rut'",
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'certificado_bancario'",
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'camara_comercio'",
    # migration 010 — liquidaciones module columns
    "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS estado_resultados_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_mandatos ADD COLUMN IF NOT EXISTS inversionista_id BIGINT REFERENCES proyecto_inversionistas(id) ON DELETE SET NULL",
    "ALTER TABLE liquidacion_mandatos ADD COLUMN IF NOT EXISTS periodo_inicio DATE",
    "ALTER TABLE liquidacion_mandatos ADD COLUMN IF NOT EXISTS periodo_fin DATE",
    "ALTER TABLE liquidacion_costos ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_costos ADD COLUMN IF NOT EXISTS nro_soporte VARCHAR(100)",
    "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS nro_soporte VARCHAR(100)",
    "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS porcentaje NUMERIC(7,4)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS base_calculo_cop NUMERIC(18,2)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS referencia_factura VARCHAR(255)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS orden INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS ingreso_neto_usd NUMERIC(18,2)",
    "ALTER TABLE proyectos ALTER COLUMN cliente_id DROP NOT NULL",
    # enum values for liquidaciones
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'despacho'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'ventas_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'compras_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'redistribucion_ingresos'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
    "ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
    "ALTER TYPE tipo_venta_liq_enum ADD VALUE IF NOT EXISTS 'autoconsumo'",
    # migration 011 — PPA many-to-many refactor + add all new columns
    # Add new columns (safe if they already exist)
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS nombre_interno VARCHAR(200)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS comprador_nombre VARCHAR(255)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS comprador_nit VARCHAR(20)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS vendedor_nombre VARCHAR(255)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS vendedor_nit VARCHAR(20)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS periodicidad_indexacion VARCHAR(50)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS periodo_indexacion_base VARCHAR(7)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS valor_indexacion_base NUMERIC(12,4)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS cantidad_minima_kwh_mes NUMERIC(14,3)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS cantidad_maxima_kwh_mes NUMERIC(14,3)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS periodicidad_facturacion VARCHAR(50)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS tiempo_pago INTEGER",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS condiciones_pago VARCHAR(500)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS gescon_codigo VARCHAR(100)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS gescon_fecha_inicio DATE",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS gescon_fecha_fin DATE",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS gescon_precio NUMERIC(12,4)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS gescon_cantidades_kwh NUMERIC(14,3)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS codigo_sic VARCHAR(50)",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    # migration 013 — PPA linked to clientes as comprador/vendedor
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS comprador_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS vendedor_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
    # Drop stale columns from old schema
    "ALTER TABLE ppa_contratos DROP COLUMN IF EXISTS proyecto_id",
    # Create the join table (idempotent)
    """CREATE TABLE IF NOT EXISTS ppa_contrato_proyectos (
        contrato_id BIGINT NOT NULL REFERENCES ppa_contratos(id) ON DELETE CASCADE,
        proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
        PRIMARY KEY (contrato_id, proyecto_id)
    )""",
    # migration 012 — ASIC / GESCON tables
    "CREATE TYPE tipo_solicitud_asic_enum AS ENUM ('registro', 'modificacion', 'terminacion', 'desistimiento')",
    "CREATE TYPE estado_solicitud_asic_enum AS ENUM ('en_proceso', 'publicado', 'rechazado', 'desistido')",
    """CREATE TABLE IF NOT EXISTS asic_solicitudes (
        id BIGSERIAL PRIMARY KEY,
        proyecto_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL,
        requerimiento_asic VARCHAR(20),
        tipo_solicitud tipo_solicitud_asic_enum NOT NULL,
        prioridad_limitacion INTEGER,
        codigo_sic_contrato VARCHAR(20),
        codigo_sic_vendedor VARCHAR(10),
        codigo_sic_comprador VARCHAR(10),
        contrato_interno VARCHAR(100),
        nombre_contacto_solicitante VARCHAR(255),
        fecha_solicitud DATE,
        fecha_inicio DATE,
        fecha_fin DATE,
        tipo_mercado VARCHAR(50) DEFAULT 'No regulado',
        tipo_asignacion VARCHAR(100),
        porcentaje_fncer NUMERIC(5,2),
        porcentaje_despacho NUMERIC(5,2),
        estado_solicitud estado_solicitud_asic_enum NOT NULL DEFAULT 'en_proceso',
        observaciones TEXT,
        link_archivo VARCHAR(1000),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_asic_codigo_sic ON asic_solicitudes (codigo_sic_contrato)",
    "CREATE INDEX IF NOT EXISTS ix_asic_proyecto ON asic_solicitudes (proyecto_id)",
    "CREATE INDEX IF NOT EXISTS ix_asic_estado_sic_fecha ON asic_solicitudes (estado_solicitud, codigo_sic_contrato, fecha_solicitud DESC NULLS LAST)",
    """CREATE TABLE IF NOT EXISTS asic_cambios_contratos (
        id BIGSERIAL PRIMARY KEY,
        solicitud_id BIGINT REFERENCES asic_solicitudes(id) ON DELETE SET NULL,
        codigo_sic_contrato VARCHAR(20),
        contrato_interno VARCHAR(100),
        proyecto_original_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL,
        codigo_frt_original VARCHAR(20),
        energia_mensual_mwh_original NUMERIC(10,3),
        proyecto_nuevo_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL,
        codigo_frt_nuevo VARCHAR(20),
        energia_mensual_mwh_nuevo NUMERIC(10,3),
        accion VARCHAR(100),
        nombre_archivo VARCHAR(500),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    # migration 013 — Fronteras extended GESCON fields + diccionario + asic nombre_interno
    "ALTER TABLE fronteras ALTER COLUMN proyecto_id DROP NOT NULL",
    "ALTER TYPE tipo_frontera_enum ADD VALUE IF NOT EXISTS 'consumo_auxiliar'",
    "ALTER TYPE tipo_frontera_enum ADD VALUE IF NOT EXISTS 'consumo_propio'",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS registrada_por VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nit VARCHAR(20)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nivel_tension INTEGER",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS transferencia_maxima_kwh NUMERIC(14,3)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS representante_frontera VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_inicio_representacion DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS operador_red VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS operador_red_zona VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nombre_cgm VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS predio_id VARCHAR(50)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nombre_predio VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS representante_ddv VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nro_serie_med_ppal VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS marca_med_ppal VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS modelo_med_ppal VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS clase_medidor VARCHAR(50)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS num_elementos_med_ppal INTEGER",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_cambio_med_ppal DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS entidad_calibradora_med_ppal VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_calibracion_med_ppal DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_actualizacion_ppal DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS nro_serie_med_resp VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS marca_med_resp VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS modelo_med_resp VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS num_elementos_med_resp INTEGER",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_cambio_med_resp DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS entidad_calibradora_med_resp VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_calibracion_med_resp DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS fecha_actualizacion_resp DATE",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS factor_perdidas_frontera_principal NUMERIC(10,6)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS codigo_ciiu VARCHAR(20)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS clasificacion_industrial_general VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS clasificacion_industrial_especifica VARCHAR(255)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS codigo_sic_frontera_generacion VARCHAR(50)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS potencia_maxima_declarada NUMERIC(10,4)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS tipo_tecnologia VARCHAR(100)",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS codigo_sic_frontera_usuario VARCHAR(50)",
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS nombre_interno VARCHAR(200)",
    """CREATE TABLE IF NOT EXISTS gescon_diccionario_contratos (
        id BIGSERIAL PRIMARY KEY,
        codigo_contrato VARCHAR(100) NOT NULL UNIQUE,
        nombre VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    # migration 014 — contratos_servicio: vinculación clientes + campos CGM/Promotor/REC
    "ALTER TABLE contratos_servicio ALTER COLUMN proyecto_id DROP NOT NULL",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS contratante_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS prestador_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tiene_cgm BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tiene_promotor BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS cgm_codigo_sic VARCHAR(20)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS cgm_porcentaje_fncer NUMERIC(5,2)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS cgm_tipo_asignacion VARCHAR(100)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS promotor_tarifa NUMERIC(12,4)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS promotor_condiciones TEXT",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS rec_cantidad NUMERIC(14,3)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS rec_precio_unitario NUMERIC(12,4)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS rec_vintage VARCHAR(20)",
    "ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'rec'",
    # migration 015 — correo_operacional en clientes
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_operacional VARCHAR(255)",
    # MGS alarms table
    """CREATE TABLE IF NOT EXISTS alarmas_monitoreo (
        id BIGSERIAL PRIMARY KEY,
        proyecto_nombre VARCHAR(255) NOT NULL,
        severity VARCHAR(20) NOT NULL,
        alarm_type VARCHAR(50) NOT NULL,
        details TEXT NOT NULL,
        source_data JSONB,
        resolved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_alarmas_monitoreo_created ON alarmas_monitoreo (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_alarmas_monitoreo_severity ON alarmas_monitoreo (severity) WHERE resolved_at IS NULL",
    # Cross-database correlation columns
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS origina_code VARCHAR(100)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS requestsdb_supply_id BIGINT",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_node_name VARCHAR(255)",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_origina_code ON proyectos (origina_code) WHERE origina_code IS NOT NULL",
    # migration 016 — informes_guardados: flujo editorial de informes operacionales
    """CREATE TABLE IF NOT EXISTS informes_guardados (
        id BIGSERIAL PRIMARY KEY,
        tipo VARCHAR(20) NOT NULL,
        sub_project VARCHAR(200) NOT NULL,
        periodo_desde VARCHAR(10) NOT NULL,
        periodo_hasta VARCHAR(10) NOT NULL,
        periodo_display VARCHAR(100),
        proyecto_nombre VARCHAR(300),
        html_content TEXT NOT NULL,
        charts_data JSONB,
        estado VARCHAR(20) NOT NULL DEFAULT 'borrador',
        creado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
        editado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
        aprobado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
        creado_por_nombre VARCHAR(255),
        editado_por_nombre VARCHAR(255),
        aprobado_por_nombre VARCHAR(255),
        creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        editado_en TIMESTAMPTZ,
        aprobado_en TIMESTAMPTZ,
        correo_enviado BOOLEAN NOT NULL DEFAULT FALSE,
        correo_enviado_en TIMESTAMPTZ
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_informes_tipo_sp_periodo ON informes_guardados (tipo, sub_project, periodo_desde, periodo_hasta)",
    "CREATE INDEX IF NOT EXISTS ix_informes_sub_project ON informes_guardados (sub_project)",
    "CREATE INDEX IF NOT EXISTS ix_informes_estado ON informes_guardados (estado)",
    "CREATE INDEX IF NOT EXISTS ix_informes_editado_en ON informes_guardados (editado_en DESC NULLS LAST)",
    # migration 017 — Climate indices + energy price history + forecasts
    """CREATE TABLE IF NOT EXISTS clima_oni_monthly (
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
    )""",
    """CREATE TABLE IF NOT EXISTS clima_precip_monthly (
        id BIGSERIAL PRIMARY KEY,
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        region VARCHAR(50) NOT NULL,
        precip_mm REAL NOT NULL,
        anomaly_pct REAL,
        climatology_mm REAL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(year, month, region)
    )""",
    """CREATE TABLE IF NOT EXISTS clima_price_monthly (
        id BIGSERIAL PRIMARY KEY,
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        price_cop_kwh REAL NOT NULL,
        enso_phase VARCHAR(20),
        precip_andina_mm REAL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE(year, month)
    )""",
    """CREATE TABLE IF NOT EXISTS clima_forecasts (
        id BIGSERIAL PRIMARY KEY,
        forecast_date DATE NOT NULL,
        forecast_json JSONB NOT NULL,
        model_version VARCHAR(50) DEFAULT 'v1_statistical',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_clima_oni_ym ON clima_oni_monthly (year, month)",
    "CREATE INDEX IF NOT EXISTS ix_clima_precip_ym ON clima_precip_monthly (year, month, region)",
    "CREATE INDEX IF NOT EXISTS ix_clima_price_ym ON clima_price_monthly (year, month)",
    "CREATE INDEX IF NOT EXISTS ix_clima_forecasts_date ON clima_forecasts (forecast_date DESC)",
    # migration 018 — Precios de bolsa XM (hourly history + daily aggregates)
    """CREATE TABLE IF NOT EXISTS precios_bolsa_diario (
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
    )""",
    """CREATE TABLE IF NOT EXISTS precios_bolsa_horario (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_precios_bolsa_diario_fecha ON precios_bolsa_diario (fecha DESC)",
    "CREATE INDEX IF NOT EXISTS ix_precios_bolsa_horario_fecha ON precios_bolsa_horario (fecha DESC, hora)",
    # ── DB audit P0-2: audit_log table ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        tabla VARCHAR(100) NOT NULL,
        registro_id BIGINT NOT NULL,
        accion VARCHAR(10) NOT NULL,
        usuario_id BIGINT,
        usuario_nombre VARCHAR(255),
        cambios JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_tabla_registro ON audit_log (tabla, registro_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_created ON audit_log (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_usuario ON audit_log (usuario_id) WHERE usuario_id IS NOT NULL",
    # ── DB audit P2-4: missing performance indexes ──────────────────────────
    "CREATE INDEX IF NOT EXISTS ix_proyectos_estado ON proyectos (estado)",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_cliente ON proyectos (cliente_id) WHERE cliente_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_fallas_estado_proyecto ON fallas (estado_id, proyecto_id)",
    "CREATE INDEX IF NOT EXISTS ix_fallas_fecha_identificacion ON fallas (fecha_identificacion DESC NULLS LAST)",
    "CREATE INDEX IF NOT EXISTS ix_liquidaciones_proyecto_periodo ON liquidaciones (proyecto_id, periodo)",
    "CREATE INDEX IF NOT EXISTS ix_ppa_comprador ON ppa_contratos (comprador_id) WHERE comprador_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_fronteras_proyecto ON fronteras (proyecto_id) WHERE proyecto_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_fronteras_codigo ON fronteras (codigo_frontera) WHERE codigo_frontera IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_clientes_nit ON clientes (nit_cedula) WHERE nit_cedula IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_contratos_servicio_proyecto ON contratos_servicio (proyecto_id) WHERE proyecto_id IS NOT NULL",
    # ── DB audit P2-3: soft delete on critical tables ───────────────────────
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_deleted ON proyectos (deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_clientes_deleted ON clientes (deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_ppa_deleted ON ppa_contratos (deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_fallas_deleted ON fallas (deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_liquidaciones_deleted ON liquidaciones (deleted_at) WHERE deleted_at IS NOT NULL",
    # migration — PPA tipo_contrato + carpeta_link for purchase contract support
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(20) DEFAULT 'venta'",
    "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS carpeta_link VARCHAR(1000)",
    "UPDATE ppa_contratos SET tipo_contrato = 'venta' WHERE tipo_contrato IS NULL",
    # migration — ASIC coexistence flag for multi-plant SIC codes
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS reemplaza_anterior BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS es_duplicado BOOLEAN NOT NULL DEFAULT FALSE",
    # migration — cumplimiento_mensual: PPA compliance snapshots
    "CREATE TYPE estado_cumplimiento_enum AS ENUM ('pendiente', 'cerrado', 'facturado')",
    """CREATE TABLE IF NOT EXISTS cumplimiento_mensual (
        id BIGSERIAL PRIMARY KEY,
        contrato_ppa_id BIGINT NOT NULL REFERENCES ppa_contratos(id) ON DELETE CASCADE,
        proyecto_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL,
        anio INTEGER NOT NULL,
        mes INTEGER NOT NULL,
        gen_total_mwh NUMERIC(14,3),
        compromiso_mwh NUMERIC(14,3),
        compras_bolsa_mwh NUMERIC(14,3),
        excedentes_bolsa_mwh NUMERIC(14,3),
        precio_bolsa_promedio NUMERIC(12,4),
        compras_bolsa_cop NUMERIC(18,2),
        excedentes_bolsa_cop NUMERIC(18,2),
        estado estado_cumplimiento_enum NOT NULL DEFAULT 'pendiente',
        tarifa_ppa_cop_mwh NUMERIC(12,4),
        valoracion_contrato_cop NUMERIC(18,2),
        liquidacion_id BIGINT REFERENCES liquidaciones(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(contrato_ppa_id, anio, mes)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_cumplimiento_contrato ON cumplimiento_mensual (contrato_ppa_id)",
    "CREATE INDEX IF NOT EXISTS ix_cumplimiento_periodo ON cumplimiento_mensual (anio, mes)",
    "CREATE INDEX IF NOT EXISTS ix_cumplimiento_estado ON cumplimiento_mensual (estado)",
    # migration — Fallas: MGS alarm link + impact + documentation fields
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS alarma_monitoreo_id BIGINT",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS kwh_perdidos_estimado NUMERIC(14,3)",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS impacto_economico_cop NUMERIC(16,2)",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS causa_raiz TEXT",
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS acciones_correctivas TEXT",
    "CREATE INDEX IF NOT EXISTS ix_fallas_alarma_monitoreo ON fallas (alarma_monitoreo_id) WHERE alarma_monitoreo_id IS NOT NULL",
    # migration — Password recovery fields on usuarios
    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(255)",
    "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ",
    # migration — Client contact & banking fields
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS departamento VARCHAR(100)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS banco VARCHAR(200)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS tipo_cuenta VARCHAR(50)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS numero_cuenta VARCHAR(50)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS titular_cuenta VARCHAR(255)",
    # migration — Notificaciones table
    "CREATE TYPE tipo_notificacion_enum AS ENUM ('alerta', 'info', 'accion')",
    """CREATE TABLE IF NOT EXISTS notificaciones (
        id BIGSERIAL PRIMARY KEY,
        usuario_id BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        tipo tipo_notificacion_enum NOT NULL,
        titulo VARCHAR(500) NOT NULL,
        mensaje TEXT NOT NULL,
        leida BOOLEAN NOT NULL DEFAULT FALSE,
        link VARCHAR(1000),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_notificaciones_usuario ON notificaciones (usuario_id)",
    "CREATE INDEX IF NOT EXISTS ix_notificaciones_leida ON notificaciones (usuario_id, leida) WHERE leida = FALSE",
    # migration — fronteras: quoia_meter_id + estado_operacional + soft delete
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS quoia_meter_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_fronteras_quoia_meter ON fronteras (quoia_meter_id) WHERE quoia_meter_id IS NOT NULL",
    "CREATE TYPE estado_operacional_enum AS ENUM ('activo', 'inactivo', 'en_registro', 'descomisionado')",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS estado_operacional estado_operacional_enum DEFAULT 'activo'",
    "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS ix_fronteras_soft_deleted ON fronteras (deleted_at) WHERE deleted_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_fronteras_estado_op ON fronteras (estado_operacional) WHERE estado_operacional IS NOT NULL",
    # migration — ASIC: XM tracking fields
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS fecha_envio_xm DATE",
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS fecha_respuesta_xm DATE",
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS numero_radicado VARCHAR(100)",
    "CREATE INDEX IF NOT EXISTS ix_asic_radicado ON asic_solicitudes (numero_radicado) WHERE numero_radicado IS NOT NULL",
    # migration — email_envios: send logging
    """CREATE TABLE IF NOT EXISTS email_envios (
        id BIGSERIAL PRIMARY KEY,
        destinatario VARCHAR(500) NOT NULL,
        cc TEXT,
        asunto VARCHAR(500) NOT NULL,
        tipo VARCHAR(50) NOT NULL,
        exitoso BOOLEAN NOT NULL DEFAULT TRUE,
        error TEXT,
        enviado_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_email_envios_tipo ON email_envios (tipo)",
    "CREATE INDEX IF NOT EXISTS ix_email_envios_at ON email_envios (enviado_at DESC)",
    # migration — correlation_sync_log: track sync runs
    """CREATE TABLE IF NOT EXISTS correlation_sync_log (
        id BIGSERIAL PRIMARY KEY,
        synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        projects_processed INTEGER NOT NULL DEFAULT 0,
        correlations_updated INTEGER NOT NULL DEFAULT 0,
        origina_found INTEGER NOT NULL DEFAULT 0,
        requestsdb_found INTEGER NOT NULL DEFAULT 0,
        error TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_correlation_sync_at ON correlation_sync_log (synced_at DESC)",
    # migration — investment fund correlation on clientes
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS origina_investment_id BIGINT",
    "CREATE INDEX IF NOT EXISTS ix_clientes_origina_investment ON clientes (origina_investment_id) WHERE origina_investment_id IS NOT NULL",
    # migration — ASIC porcentaje_despacho domain constraint (fix bad data first)
    "UPDATE asic_solicitudes SET porcentaje_despacho = porcentaje_despacho / 100.0 WHERE porcentaje_despacho > 1.0",
    "ALTER TABLE asic_solicitudes ADD CONSTRAINT chk_porcentaje_despacho CHECK (porcentaje_despacho >= 0 AND porcentaje_despacho <= 1.0)",
    # migration — ASIC ↔ PPA foreign key
    "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS contrato_ppa_id BIGINT REFERENCES ppa_contratos(id)",
    "CREATE INDEX IF NOT EXISTS ix_asic_contrato_ppa ON asic_solicitudes (contrato_ppa_id) WHERE contrato_ppa_id IS NOT NULL",
    # migration — fronteras_lecturas dedup constraint
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_fronteras_lecturas_frontera_fuente_fecha ON fronteras_lecturas (frontera_id, fuente, fecha_hora)",
    # migration — liquidacion_xm_datos (datos XM por frontera para PPA/GD)
    """CREATE TABLE IF NOT EXISTS liquidacion_xm_datos (
        id BIGSERIAL PRIMARY KEY,
        liquidacion_id BIGINT NOT NULL REFERENCES liquidaciones(id) ON DELETE CASCADE,
        frontera_id BIGINT REFERENCES fronteras(id) ON DELETE SET NULL,
        tipo_venta TEXT NOT NULL,
        energia_kwh NUMERIC(14,3) NOT NULL,
        tarifa_aplicada_kwh NUMERIC(12,6) NOT NULL,
        valor_bruto_cop NUMERIC(18,2) NOT NULL,
        referencia_factura_xm VARCHAR(100),
        fecha_factura_xm DATE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_liquidacion_xm_datos_liq ON liquidacion_xm_datos (liquidacion_id)",
    "CREATE INDEX IF NOT EXISTS ix_liquidacion_xm_datos_frt ON liquidacion_xm_datos (frontera_id) WHERE frontera_id IS NOT NULL",
    # migration — fecha_fin_representacion en proyectos
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_fin_representacion DATE",
    # migration — missing updated_at on liquidacion child tables
    "ALTER TABLE liquidacion_costos ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    # migration — ASIC 'terminado' estado
    "ALTER TYPE estado_solicitud_asic_enum ADD VALUE IF NOT EXISTS 'terminado'",
    # retroactive: mark registros terminated by existing terminación records
    """UPDATE asic_solicitudes AS target
       SET estado_solicitud = 'terminado'
       FROM asic_solicitudes AS term
       WHERE term.tipo_solicitud = 'terminacion'
         AND term.estado_solicitud = 'publicado'
         AND target.codigo_sic_contrato = term.codigo_sic_contrato
         AND target.contrato_interno = term.contrato_interno
         AND target.id != term.id
         AND target.estado_solicitud = 'publicado'
         AND target.tipo_solicitud IN ('registro', 'modificacion')
         AND (term.proyecto_id IS NULL OR target.proyecto_id = term.proyecto_id)""",
    # migration — api_keys: API token management for external integrations
    """CREATE TABLE IF NOT EXISTS api_keys (
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
    )""",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_usuario ON api_keys (usuario_id)",
    "CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON api_keys (key_prefix)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys (key_hash)",
    # fix — garantizar que operaciones@unergy.io tenga rol operaciones
    # (si el rol actual no permite acceso a la sección Informes/Fallas/Monitoreo)
    """UPDATE usuarios
       SET rol = 'operaciones'
       WHERE email = 'operaciones@unergy.io'
         AND rol::text NOT IN ('admin', 'operaciones', 'monitoreo')""",
    # migration 019 — tarifa_mensual + indexación O&M JSONB en contratos_servicio
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tarifa_mensual NUMERIC(14,2)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS indexacion_anual JSONB",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS indexacion_mensual JSONB",
    # migration 020 — facturas Solenium e Inversionistas como JSONB
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS facturas_solenium JSONB",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS facturas_inversionistas JSONB",
    # migration 021 — pipeline de verificación de informes
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS comentarios JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS enviado_por_id BIGINT REFERENCES usuarios(id) ON DELETE SET NULL",
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS enviado_por_nombre VARCHAR(255)",
    # fix — informes_guardados: correo_enviado/correo_enviado_en pueden faltar si la
    # tabla se creó antes de que se añadieran al modelo. ALTER TABLE IF NOT EXISTS es idempotente.
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS correo_enviado BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS correo_enviado_en TIMESTAMPTZ",
    # migration 022 — portafolio compuesto: miembros (proyectos) del informe de portafolio
    "ALTER TABLE informes_guardados ADD COLUMN IF NOT EXISTS miembros JSONB",
    # migration 023 — gestión de portafolios (capas de proyectos)
    """CREATE TABLE IF NOT EXISTS portafolios (
        id BIGSERIAL PRIMARY KEY,
        nombre VARCHAR(255) UNIQUE NOT NULL,
        descripcion TEXT,
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS portafolio_id BIGINT REFERENCES portafolios(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_portafolio_id ON proyectos (portafolio_id)",
    # migration 024 — contratos CGM/Representación: campos específicos
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS inversionista_nombre VARCHAR(255)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS portafolio VARCHAR(255)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS codigo_sun_factory VARCHAR(50)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tarifa_admin NUMERIC(8,4)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tarifa_cgm NUMERIC(10,6)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tarifa_representacion NUMERIC(10,6)",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS indexacion_cgm JSONB",
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS indexacion_representacion JSONB",
    # migration 025 — nombre_proyecto_ref para búsqueda fuzzy por proyecto
    "ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS nombre_proyecto_ref VARCHAR(255)",
    "CREATE INDEX IF NOT EXISTS ix_contratos_servicio_nombre_ref ON contratos_servicio (nombre_proyecto_ref) WHERE nombre_proyecto_ref IS NOT NULL",
    # migration 026 — proyecto_inversionista_id en liquidacion_facturas
    "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS proyecto_inversionista_id BIGINT REFERENCES proyecto_inversionistas(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_liquidacion_facturas_inv_id ON liquidacion_facturas (proyecto_inversionista_id) WHERE proyecto_inversionista_id IS NOT NULL",
    # migration O&M — panel mensual de facturación O&M
    """CREATE TABLE IF NOT EXISTS om_ipc_tasas (
        id          BIGSERIAL PRIMARY KEY,
        año         INTEGER NOT NULL UNIQUE,
        tasa        NUMERIC(8,6) NOT NULL,
        confirmado  BOOLEAN NOT NULL DEFAULT FALSE,
        fuente      VARCHAR(100),
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS om_seleccion_mensual (
        id          BIGSERIAL PRIMARY KEY,
        contrato_id BIGINT NOT NULL REFERENCES contratos_servicio(id) ON DELETE CASCADE,
        periodo     VARCHAR(7) NOT NULL,
        incluido    BOOLEAN NOT NULL DEFAULT TRUE,
        facturado   BOOLEAN NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_om_seleccion_contrato_periodo UNIQUE (contrato_id, periodo)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_om_seleccion_periodo ON om_seleccion_mensual (periodo)",
    "CREATE INDEX IF NOT EXISTS ix_om_seleccion_contrato ON om_seleccion_mensual (contrato_id)",
    # Factura consolidada mensual del proveedor
    """CREATE TABLE IF NOT EXISTS om_factura_mensual (
        id             BIGSERIAL PRIMARY KEY,
        periodo        VARCHAR(7) NOT NULL UNIQUE,
        nombre_archivo VARCHAR(500),
        enlace_pdf     VARCHAR(2000),
        ruta_local     VARCHAR(1000),
        subido_en      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_om_factura_periodo ON om_factura_mensual (periodo)",
    # migration — garantias_ajustes: ajustes XM (semanal/txr/mensual)
    "CREATE TYPE tipo_ajuste_xm_enum AS ENUM ('semanal', 'txr', 'mensual')",
    """CREATE TABLE IF NOT EXISTS garantias_ajustes (
    id BIGSERIAL PRIMARY KEY,
    tipo tipo_ajuste_xm_enum NOT NULL,
    fecha DATE NOT NULL,
    pb NUMERIC(18,2), restricciones NUMERIC(18,2), stn NUMERIC(18,2),
    trm NUMERIC(18,2), ptb NUMERIC(18,2), total_ungc NUMERIC(18,2),
    total_ungg NUMERIC(18,2), total_consignar NUMERIC(18,2),
    disponible_custodia NUMERIC(18,2), congelado NUMERIC(18,2),
    saldo NUMERIC(18,2), total_ajuste_txr NUMERIC(18,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)""",
    "CREATE INDEX IF NOT EXISTS ix_garantias_ajustes_fecha ON garantias_ajustes (fecha)",
    "ALTER TABLE garantias_ajustes ADD COLUMN IF NOT EXISTS snapshot JSONB",
    # migration — Panel Contable (preliquidaciones / liquidaciones oficiales)
    """CREATE TABLE IF NOT EXISTS panel_contable (
        id BIGSERIAL PRIMARY KEY,
        proyecto_id BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
        periodo VARCHAR(7) NOT NULL,
        tipo VARCHAR(20) NOT NULL DEFAULT 'preliquidacion',
        liquidar BOOLEAN NOT NULL DEFAULT TRUE,
        generar_mandatos BOOLEAN NOT NULL DEFAULT FALSE,
        tiene_bolsa BOOLEAN NOT NULL DEFAULT FALSE,
        tiene_costos BOOLEAN NOT NULL DEFAULT FALSE,
        ingreso_bruto_cop NUMERIC(18,2),
        comercializador VARCHAR(120),
        fecha_firma DATE,
        consecutivo_ingresos INTEGER,
        consecutivo_costos INTEGER,
        er_filename VARCHAR(300),
        generado_por_id BIGINT REFERENCES usuarios(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_panel_proyecto_periodo_tipo ON panel_contable (proyecto_id, periodo, tipo)",
    "CREATE INDEX IF NOT EXISTS ix_panel_periodo_tipo ON panel_contable (periodo, tipo)",
    """CREATE TABLE IF NOT EXISTS panel_contable_linea (
        id BIGSERIAL PRIMARY KEY,
        panel_id BIGINT NOT NULL REFERENCES panel_contable(id) ON DELETE CASCADE,
        proyecto_inversionista_id BIGINT REFERENCES proyecto_inversionistas(id) ON DELETE SET NULL,
        inversionista_nombre VARCHAR(255),
        porcentaje NUMERIC(10,7),
        grupo VARCHAR(20) NOT NULL,
        concepto VARCHAR(255) NOT NULL,
        valor_cop NUMERIC(18,2),
        comprobante_contable VARCHAR(120),
        orden INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_panel_linea_panel ON panel_contable_linea (panel_id)",
    # Panel Contable — liquidación de ingresos y costos independientes
    "ALTER TABLE panel_contable ADD COLUMN IF NOT EXISTS liquidar_ingresos BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE panel_contable ADD COLUMN IF NOT EXISTS liquidar_costos BOOLEAN NOT NULL DEFAULT TRUE",
]


# ── DDLs extraídos de init_db.add_columns() (no cubiertos arriba) ───────────────
_INIT_DB_DDLS = [
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sub_project VARCHAR(50)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_bitacora VARCHAR(255)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_clientes VARCHAR(255)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS srv_operacion BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cantidad_total_paneles INTEGER",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
    "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS informe_html TEXT",
    "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS informe_actualizado_en TIMESTAMPTZ",
]


def _split_ddls(stmts):
    """Separa las sentencias ALTER TYPE … ADD VALUE (deben correr en AUTOCOMMIT,
    fuera de un bloque de transacción) del resto del DDL, preservando el orden."""
    add_value = [s for s in stmts if "ADD VALUE" in s.upper()]
    regular = [s for s in stmts if "ADD VALUE" not in s.upper()]
    return add_value, regular


def upgrade() -> None:
    bind = op.get_bind()
    all_stmts = _PENDING_DDLS + _INIT_DB_DDLS
    add_value_stmts, regular_stmts = _split_ddls(all_stmts)

    # ALTER TYPE … ADD VALUE debe correr fuera de un bloque de transacción.
    # Se ejecuta primero, en conexiones AUTOCOMMIT separadas, para que los nuevos
    # valores enum existan antes del DDL regular que los referencia.
    for stmt in add_value_stmts:
        try:
            with bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
        except Exception as e:  # noqa: BLE001 — idempotencia: tolerar objetos ya existentes
            print(f"[migration 022 ddl skipped] {e}")

    # DDL regular: cada sentencia en su propio SAVEPOINT para tolerar fallos
    # (p.ej. CREATE TYPE sin IF NOT EXISTS sobre un tipo ya creado por create_all)
    # sin abortar la transacción de la migración completa.
    for stmt in regular_stmts:
        try:
            with bind.begin_nested():
                bind.execute(text(stmt))
        except Exception as e:  # noqa: BLE001 — idempotencia
            print(f"[migration 022 ddl skipped] {e}")


def downgrade() -> None:
    # DDL aditivo e idempotente; no se revierte automáticamente. El downgrade
    # del esquema base lo maneja la migración 021 (drop_all).
    pass
