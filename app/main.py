from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, SessionLocal
from app.api.v1.router import api_router

# Idempotent DDL run at startup — safe to run on every boot
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
]


def _run_column_migrations() -> None:
    add_value_stmts = [s for s in _PENDING_DDLS if "ADD VALUE" in s.upper()]
    regular_stmts = [s for s in _PENDING_DDLS if "ADD VALUE" not in s.upper()]

    # ALTER TYPE … ADD VALUE must run outside a transaction block in PostgreSQL.
    # Run first so new enum values exist before any regular DDL that references them.
    for stmt in add_value_stmts:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
        except Exception as e:
            print(f"[startup ddl skipped] {e}")

    if regular_stmts:
        with engine.connect() as conn:
            for stmt in regular_stmts:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[startup ddl skipped] {e}")


_CAT_META = {
    "Fallas de Medición":                       {"codigo": "1", "icono": "📡", "color": "#60A5FA", "orden": 1},
    "Fallas Eléctricas":                        {"codigo": "2", "icono": "⚡", "color": "#F6FF72", "orden": 2},
    "Fallas por Eventos Adversos":              {"codigo": "3", "icono": "🌩️", "color": "#FF5757", "orden": 3},
    "Fallos por Desgaste / Degradación":        {"codigo": "4", "icono": "🔧", "color": "#F97316", "orden": 4},
    "Fallas Civiles / Estructurales":           {"codigo": "5", "icono": "🏗️", "color": "#C47AFF", "orden": 5},
    "Fallas HSE / Seguridad Laboral":           {"codigo": "6", "icono": "🦺", "color": "#4ADE80", "orden": 6},
    "Fallas BESS / Almacenamiento (si aplica)": {"codigo": "7", "icono": "🔋", "color": "#7EC8E3", "orden": 7},
    "Fallas Administrativas / Regulatorias":    {"codigo": "8", "icono": "📋", "color": "#F4A460", "orden": 8},
    "Sin Suministro Eléctrico en el Proyecto":  {"codigo": "9", "icono": "🔌", "color": "#FF6B6B", "orden": 9},
}


def _run_catalog_seed() -> None:
    import json as _json
    from sqlalchemy.orm import sessionmaker
    from app.models.fallas import FallaCatCategoria, FallaCatTipo

    data_file = Path("data/fallas_clasificadas_unergy.json")
    if not data_file.exists():
        print("[catalog seed] data/fallas_clasificadas_unergy.json not found, skipping")
        return

    try:
        data = _json.loads(data_file.read_text(encoding="utf-8"))
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            for cat_name, meta in _CAT_META.items():
                existing = db.query(FallaCatCategoria).filter_by(codigo=meta["codigo"]).first()
                if existing:
                    existing.etiqueta = cat_name
                    existing.icono = meta["icono"]
                    existing.color_hex = meta["color"]
                    existing.orden = meta["orden"]
                    existing.activa = True
                else:
                    db.add(FallaCatCategoria(
                        codigo=meta["codigo"], etiqueta=cat_name,
                        icono=meta["icono"], color_hex=meta["color"],
                        orden=meta["orden"], activa=True,
                    ))
            db.flush()

            for entry in data:
                cat_name = entry.get("Categoría", "").strip()
                code = entry.get("Código de Falla", "").strip()
                evento = entry.get("Evento", "").strip()
                desc = entry.get(
                    "Descripción detallada de la actividad (requisitos, controles, documentos)", ""
                ).strip()
                if not code or not evento:
                    continue
                meta = _CAT_META.get(cat_name)
                if not meta:
                    continue
                cat_obj = db.query(FallaCatCategoria).filter_by(codigo=meta["codigo"]).first()
                if not cat_obj:
                    continue
                existing_tipo = db.query(FallaCatTipo).filter_by(codigo=code).first()
                if existing_tipo:
                    existing_tipo.etiqueta = evento
                    existing_tipo.descripcion = desc
                    existing_tipo.categoria_id = cat_obj.id
                    existing_tipo.activa = True
                else:
                    db.add(FallaCatTipo(
                        categoria_id=cat_obj.id, codigo=code,
                        etiqueta=evento, descripcion=desc, activa=True,
                    ))
            db.commit()
            print(f"[catalog seed] OK — {len(data)} tipos procesados")
        except Exception as e:
            db.rollback()
            print(f"[catalog seed] ERROR: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[catalog seed] skipped: {e}")


# old categoria codigo → best new tipo code (most representative)
_OLD_CAT_TO_TIPO = {
    "medicion":    "1.1",   # Pérdida de comunicación de inversores
    "comunicacion": "1.1",
    "inversor":    "2.8",   # Falla de inversor
    "red":         "2.1",   # Pérdida de red eléctrica (utility)
    "produccion":  "4.6",   # Inversor con derating o eficiencia reducida
    "estructura":  "5.1",   # Daño en cimentación o anclaje
    "otro":        "2.0",   # Desconexión sin causa identificada
}


def _run_tipo_migration() -> None:
    """Re-point faults that use old snake_case tipo codes to the new numeric ones."""
    import re
    from sqlalchemy.orm import sessionmaker, joinedload
    from app.models.fallas import Falla, FallaCatTipo

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        numeric_pattern = re.compile(r'^\d+\.\d+$')

        new_tipos: dict[str, int] = {
            t.codigo: t.id
            for t in db.query(FallaCatTipo).filter(FallaCatTipo.activa == True).all()
            if numeric_pattern.match(t.codigo or "")
        }
        if not new_tipos:
            print("[tipo migration] No new numeric tipos found — run catalog seed first")
            return

        old_tipos = (
            db.query(FallaCatTipo)
            .options(joinedload(FallaCatTipo.categoria))
            .all()
        )
        old_tipos = [t for t in old_tipos if not numeric_pattern.match(t.codigo or "")]

        if not old_tipos:
            print("[tipo migration] No old tipos found — already clean")
            return

        updated_total = 0
        for old_t in old_tipos:
            cat_code = old_t.categoria.codigo if old_t.categoria else ""
            target_code = _OLD_CAT_TO_TIPO.get(cat_code, "2.0")
            new_id = new_tipos.get(target_code) or new_tipos.get("2.0")
            if not new_id:
                continue
            n = (
                db.query(Falla)
                .filter(Falla.tipo_id == old_t.id)
                .update({"tipo_id": new_id}, synchronize_session=False)
            )
            if n:
                print(f"[tipo migration] {n} fallas: {old_t.codigo!r} → {target_code}")
            updated_total += n

        db.commit()
        if updated_total:
            print(f"[tipo migration] ✅ {updated_total} fallas migradas")
        else:
            print("[tipo migration] Nada que migrar")
    except Exception as e:
        db.rollback()
        print(f"[tipo migration] ERROR: {e}")
    finally:
        db.close()


def _run_srv_operacion_sync() -> None:
    """Marca srv_operacion=True para proyectos que:
    - Tienen registro en servicio_operacion (relación explícita), o
    - Son de tipo autoconsumo/minigranja y están en operación.
    Idempotente — solo actualiza filas que aún tienen el campo en False/NULL.
    """
    stmts = [
        # Proyectos con ServicioOperacion explícito
        """
        UPDATE proyectos SET srv_operacion = TRUE
        WHERE id IN (SELECT proyecto_id FROM servicio_operacion)
          AND (srv_operacion IS NULL OR srv_operacion = FALSE)
        """,
        # Proyectos autoconsumo y minigranja en operación
        """
        UPDATE proyectos SET srv_operacion = TRUE
        WHERE estado = 'en_operacion'
          AND tipo_proyecto IN ('autoconsumo', 'minigranja')
          AND (srv_operacion IS NULL OR srv_operacion = FALSE)
        """,
    ]
    for stmt in stmts:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(stmt))
                conn.commit()
                if result.rowcount:
                    print(f"[srv_operacion sync] {result.rowcount} proyectos actualizados")
        except Exception as e:
            print(f"[srv_operacion sync] skipped: {e}")


def _run_create_tables() -> None:
    """Create any missing tables (idempotent — skips existing tables)."""
    try:
        from app.models import Base
        Base.metadata.create_all(bind=engine)
        print("[startup] Tables ensured OK")
    except Exception as e:
        print(f"[startup] create_all skipped: {e}")


# Datos iniciales de contratos CGM/Representación — fuente: Data/contratosCGM.json
# Indexaciones Ayura 1 (firma 2024-10-11, tarifa base 5 $/kWh)
_IDX_AYURA1 = [
    {"año": 2024, "ipc": None, "valor": 5.0,     "esBase": True},
    {"año": 2025, "ipc": 5.2,  "valor": 5.26},
    {"año": 2026, "ipc": 5.1,  "valor": 5.52826},
]
_SOPORTE_AYURA1 = "https://drive.google.com/file/d/1y8m6vU3SNumR85BNcVGBgTEfqZnq0PJ_/view?usp=sharing"

# Indexaciones "Legalizar" firma 2024 (mismas tasas que Ayurá 1)
_IDX_LEG24 = [
    {"año": 2024, "ipc": None, "valor": 5.0,     "esBase": True},
    {"año": 2025, "ipc": 5.2,  "valor": 5.26},
    {"año": 2026, "ipc": 5.1,  "valor": 5.52826},
]
# Indexaciones "Legalizar" firma 2025 (solo 2026 IPC)
_IDX_LEG25 = [
    {"año": 2025, "ipc": None, "valor": 5.0,     "esBase": True},
    {"año": 2026, "ipc": 5.1,  "valor": 5.255},
]

_CGM_CONTRATOS = [
    # ── Portafolio Ayurá 1 (inversionista inferido: Ayurá S.A.S.) ─────────────
    dict(proyecto_nombre="MiniGranja 0001 - Uruaco",          codigo_sun_factory="COLATLT14P2",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0004 - Valle de Gandalf", codigo_sun_factory="COLCEST61P3",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0005 - Canahuate",       codigo_sun_factory="COLCEST61P1",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0006 - Perija",          codigo_sun_factory="COLCEST58P2",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0007 - La Paz Vallenata", codigo_sun_factory="COLCEST9P1",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0008 - La Paz Verso",    codigo_sun_factory="COLCEST2P3",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0009 - El Molino",       codigo_sun_factory="COLLAGT19P2",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0010 - Villanueva",      codigo_sun_factory="COLLAGT27P2",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0013 - La Mesa",         codigo_sun_factory="COLSANT10P1",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0014 - El Olimpo",       codigo_sun_factory="COLSANT4P2",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="Minigranja 0016 - La Puya",         codigo_sun_factory="COLCEST45P5",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0017 - La Paz Esmeralda", codigo_sun_factory="COLCEST17P1",
         portafolio="Ayura 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),

    # ── Sol de la Sierra 1 / Legalizar contratos ──────────────────────────────
    dict(proyecto_nombre="Minigranja 0018 - La Paz Leyenda",  codigo_sun_factory="COLCEST53P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038, fecha_firma_contrato="2024-11-23",
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="MiniGranja 0019 - El Merengue",     codigo_sun_factory="COLCEST45P7",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038, fecha_firma_contrato="2025-03-28",
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG25, indexacion_representacion=_IDX_LEG25),
    dict(proyecto_nombre="MiniGranja 0019 - El Merengue",     codigo_sun_factory="COLCEST45P7",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG25, indexacion_representacion=_IDX_LEG25),
    dict(proyecto_nombre="Minigranja 0022 - La Cumbia",       codigo_sun_factory="COLCEST45P4",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="Minigranja 0023 - El Joropo",       codigo_sun_factory="COLCEST45P2",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038,
         tarifa_cgm=0.0, tarifa_representacion=0.0,
         indexacion_cgm=[], indexacion_representacion=[]),
    dict(proyecto_nombre="Minigranja 0023 - El Joropo",       codigo_sun_factory="COLCEST45P2",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=0.0, tarifa_representacion=0.0,
         indexacion_cgm=[], indexacion_representacion=[]),
    dict(proyecto_nombre="MiniGranja 0024 - San Diego Sur",   codigo_sun_factory="COLCEST38P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="MiniGranja 0024 - San Diego Sur",   codigo_sun_factory="COLCEST38P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="MiniGranja 0025 - El Copey Occidente", codigo_sun_factory="COLCEST39P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="MiniGranja 0025 - El Copey Occidente", codigo_sun_factory="COLCEST39P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="Minigranja 0026 - Valencia Oriente", codigo_sun_factory="COLCEST74P1",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),
    dict(proyecto_nombre="Minigranja 0027 - Valencia Oriente 2", codigo_sun_factory="COLCEST74P2",
         portafolio="Sol de la Sierra 1", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038,
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_LEG24, indexacion_representacion=_IDX_LEG24),

    # ── MGS Mapale ────────────────────────────────────────────────────────────
    dict(proyecto_nombre="MGS Mapale",
         inversionista_nombre="FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
         indexacion_cgm=[], indexacion_representacion=[]),
    dict(proyecto_nombre="Minigranja 0012 - La Reserva", codigo_sun_factory="COLSANT9P1",
         portafolio="Suno - Solenium - Sandra Estrada", inversionista_nombre="Strada Asociados S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-04-02",
         enlace_drive="https://drive.google.com/file/d/1MJ-zyaEgVIKiqy4XbLjakmYoI3h2Mr0u/view?usp=drive_link",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0012 - La Reserva", codigo_sun_factory="COLSANT9P1",
         portafolio="Suno - Solenium - Sandra Estrada", inversionista_nombre="Inversiones Estrada Arbelaez y CIA S. en C.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-04-02",
         enlace_drive="https://drive.google.com/file/d/18Cx6N_dB1GghULWok9SzGu79XFw47V/view?usp=drive_link",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="GD NAOS 1", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
         fecha_firma_contrato="2024-07-17",
         enlace_drive="https://drive.google.com/file/d/1u0-xNyfdvhwZk3AokNyFsGjzn8PNfgtO/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":7.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":7.364},{"año":2026,"ipc":5.1,"valor":7.739564}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":3.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":3.156},{"año":2026,"ipc":5.1,"valor":3.316956}]),
    dict(proyecto_nombre="Minigranja 0015 - El Son", codigo_sun_factory="COLCEST45P1",
         portafolio="Suno - Solenium", inversionista_nombre="Nacional de Transformadores S.A.S.",
         tarifa_admin=0.038, fecha_firma_contrato="2024-08-09",
         enlace_drive="https://drive.google.com/file/d/1mNHMt12XnT8rvGnxhE3a7Ub9MEQsQWn1/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0015 - El Son", codigo_sun_factory="COLCEST45P1",
         portafolio="Suno - Solenium", inversionista_nombre="Unergy S.A.S",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
         portafolio="Suno - Solenium", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038, fecha_firma_contrato="2024-01-19",
         enlace_drive="https://drive.google.com/file/d/1kWhy9drgx7z81URpYJ3ZjfWnj5h6GeYA/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
         portafolio="Suno - Solenium", inversionista_nombre="SOMOS BOGOTA USME SAS",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
         portafolio="Suno - Solenium", inversionista_nombre="Unergy S.A.S",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0040 - La Cacica", codigo_sun_factory="COLCEST55P1",
         portafolio="Serrania de Perija", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0041 - Las piloneras", codigo_sun_factory="COLCEST55P2",
         portafolio="Serrania de Perija", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0030 - Chima Oriente", codigo_sun_factory="COLCORT7P1",
         portafolio="Cox", inversionista_nombre="Solenium S.A.S",
         tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
         indexacion_cgm=[], indexacion_representacion=[]),
    dict(proyecto_nombre="Minigranja 0030 - Chima Oriente", codigo_sun_factory="COLCORT7P1",
         portafolio="Cox", inversionista_nombre="Ayura S.A.S.",
         tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
         indexacion_cgm=[], indexacion_representacion=[]),
    dict(proyecto_nombre="Minigranja 0021 - Ibirico", codigo_sun_factory="COLCEST49P2",
         portafolio="Kai", inversionista_nombre="FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0075 - Chiriguana Norte 2", codigo_sun_factory="COLCEST60P4",
         portafolio="Skandia", inversionista_nombre="PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="Minigranja 0077 - Chiriguana Norte 4", codigo_sun_factory="COLCEST60P2",
         portafolio="Skandia", inversionista_nombre="PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",
         tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}],
         indexacion_representacion=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True},{"año":2025,"ipc":5.2,"valor":6.312},{"año":2026,"ipc":5.1,"valor":6.633912}]),
    dict(proyecto_nombre="GD Marimonda", inversionista_nombre="LA HORMIGA SOLAR S.A.S. E.S.P.",
         fecha_firma_contrato="2025-03-17",
         enlace_drive="https://drive.google.com/file/d/1uUIroNjUcCJdNiqcSpu3LRV3a7n8yDgH/view?usp=drive_link",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="MGS Naos 2", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
         fecha_firma_contrato="2025-02-20",
         enlace_drive="https://drive.google.com/file/d/1Rjy0dVYdqcHsVU6tDtM7JQdXGdY8wMzg/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="MGS Naos 3", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
         fecha_firma_contrato="2025-04-04",
         enlace_drive="https://drive.google.com/file/d/1E7BQ5LzLs0vKNXQKJ1QfxbEOV6R9Qsjl/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="Bayunca", inversionista_nombre="PARQUE EOLICO DE GALERAZAMBA S.A.S.",
         fecha_firma_contrato="2025-04-07",
         enlace_drive="https://drive.google.com/file/d/1BHe5yoiPT9t-tBIJCLnKbREvtscu7PHx/view?usp=sharing",
         tarifa_cgm=0.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":0.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":0.0}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD Delta 1", inversionista_nombre="GRANJAS SOLARES DELTA S.A.S. E.S.P",
         fecha_firma_contrato="2025-06-11",
         enlace_drive="https://drive.google.com/file/d/1JD8jRf8UUs9PwVDpStfcF2XuCerHQyVh/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="GD Polaris 1", inversionista_nombre="GRANJA SOLAR POLARIS ENERGY S.A.S.",
         fecha_firma_contrato="2025-06-11",
         enlace_drive="https://drive.google.com/file/d/1dbTdzyy0v5nepdtILhwcYIODp8a0eoZJ/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="GD Sirius", inversionista_nombre="QUANTUM ENERGY INGENIERIA S.A.S",
         fecha_firma_contrato="2025-06-09",
         enlace_drive="https://drive.google.com/file/d/1KcgA0iKTJWkiWBp1h6EAg0CArVijcUL3/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD Biosolar", inversionista_nombre="INVERSIONES BIOSOSTENIBLES S.A.S.",
         fecha_firma_contrato="2025-06-09",
         enlace_drive="https://drive.google.com/file/d/10eR0HhJZu2SQn0h8UIhGtdUox3bXcZOU/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD Astrolumen La Garita", inversionista_nombre="Energy Investment Group SAS",
         fecha_firma_contrato="2025-06-09",
         enlace_drive="https://drive.google.com/file/d/1Wo6gmts3B1JXMlDtBVfOP88MgzDqrNP_/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD Agustin 1", inversionista_nombre="FONSAR S.A.S.",
         fecha_firma_contrato="2025-06-09",
         enlace_drive="https://drive.google.com/file/d/1dRZdu-aiRFC9ghULWok9SzGu79XFw47V/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD 1MVA SAN ONOFRE", inversionista_nombre="NOVAVALOR ENERGY SAS",
         fecha_firma_contrato="2025-07-12",
         enlace_drive="https://drive.google.com/file/d/1HgFGQzBVE51WtdQkt3KvQ9Sgav1dZQhH/view?usp=sharing",
         tarifa_cgm=0.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":0.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":0.0}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD Yuan Solar", inversionista_nombre="FEM ENERGIA S.A.S.",
         fecha_firma_contrato="2025-08-09",
         enlace_drive="https://drive.google.com/file/d/12SUYJsDy3K7WmNjN-l0CKYzPqLq9p9PO/view?usp=sharing",
         tarifa_cgm=5.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.255}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="La Catedral", inversionista_nombre="PELLETCO S.A.S.",
         fecha_firma_contrato="2025-08-22",
         enlace_drive="https://drive.google.com/file/d/1NOxvjvr8Zo6lISXvZj1Ap8KGUjcOfAFt/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD delta 2", inversionista_nombre="GRANJAS SOLARES DELTA S.A.S. E.S.P",
         fecha_firma_contrato="2025-08-25",
         enlace_drive="https://drive.google.com/file/d/1arn43qJMevk8nSCbHpdyDprO24ekseNQ/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="PSF - Yurbaqua", inversionista_nombre="ENEXA ENERGY S.A.S.",
         fecha_firma_contrato="2025-08-20",
         enlace_drive="https://drive.google.com/file/d/1D2F-_DM9UB5iLzL6wAeYA_03q6XHAzlu/view?usp=sharing",
         tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.255}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":5.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.255}]),
    dict(proyecto_nombre="GD Polaris 2", inversionista_nombre="GRANJA SOLAR POLARIS 2 S.A.S.",
         fecha_firma_contrato="2025-09-02",
         enlace_drive="https://drive.google.com/file/d/1Al9HvwvdGeC3tJGxc9S1UaJeU-0sr2Yo/view?usp=sharing",
         tarifa_cgm=7.0, tarifa_representacion=3.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":7.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":7.357}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":3.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":3.153}]),
    dict(proyecto_nombre="GD San Pelayo", inversionista_nombre="SAMBA SOLAR S.A.S.",
         fecha_firma_contrato="2025-09-05",
         enlace_drive="https://drive.google.com/file/d/1M9xdHMsjPan5unAiI01elbvWkB9oz4WN/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="Monterrey", inversionista_nombre="EXTRACTORA MONTERREY S.A.S",
         fecha_firma_contrato="2025-10-17",
         enlace_drive="https://drive.google.com/file/d/1XpkmrCBtXP1-G84VHI7VI8uk897WG1ts/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="Sol Y Cielo 7 Los Bongos", inversionista_nombre="INENERGY S.A.S",
         fecha_firma_contrato="2025-11-19",
         enlace_drive="https://drive.google.com/file/d/1Y4X_uqmtI6Xr9fizffVYHkIngnaiwyQa/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="GD La Hormiga", inversionista_nombre="BALI ENERGY S.A.S.",
         fecha_firma_contrato="2025-11-19",
         enlace_drive="https://drive.google.com/file/d/1VowW9ZZqlW96GQ7d8UxzsIZ8m7fpRMqq/view?usp=drive_link",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}]),
    dict(proyecto_nombre="Sol&Cielo 9 - Cienaga", inversionista_nombre="INENERGY S.A.S",
         fecha_firma_contrato="2025-11-19",
         enlace_drive="https://drive.google.com/file/d/1L0MbDmQF5VE53Z03o3yDSNeXLy1Qqzf0/view?usp=drive_link",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":6.0,"esBase":True},{"año":2026,"ipc":5.1,"valor":6.306}]),
    dict(proyecto_nombre="Taurus VIII", inversionista_nombre="CUMBIA SOLAR S.A.S.",
         fecha_firma_contrato="2025-12-22",
         enlace_drive="https://drive.google.com/file/d/1K1WyQqXsE1v2Vr_RIuJdt-6ZbvaI1Tfq/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}]),
    dict(proyecto_nombre="Taurus IX", inversionista_nombre="FLAUTA SOLAR SAS",
         fecha_firma_contrato="2025-12-22",
         enlace_drive="https://drive.google.com/file/d/14u3Wf7fAP7EmtYInWP6N9UP1YDcH3XwK/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}]),
    dict(proyecto_nombre="Taurus X", inversionista_nombre="ACORDEON SOLAR S.A.S.",
         fecha_firma_contrato="2025-12-22",
         enlace_drive="https://drive.google.com/file/d/13JqZAxX_HI0G3WRCp5mL9FraSSdnPr52/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}],
         indexacion_representacion=[{"año":2025,"ipc":None,"valor":5.5,"esBase":True},{"año":2026,"ipc":5.1,"valor":5.7805}]),
    dict(proyecto_nombre="GD Garza", inversionista_nombre="PULOI SOLAR S.A.S",
         fecha_firma_contrato="2026-01-22",
         enlace_drive="https://drive.google.com/file/d/1nXWG8ZiwUVZm9LcwydXU7IcDAyuLICU8/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}]),
    dict(proyecto_nombre="La Perdiz", inversionista_nombre="MONOCUCO SOLAR S.A.S.",
         fecha_firma_contrato="2026-01-22",
         enlace_drive="https://drive.google.com/file/d/1vT2OAng0d5SgXMJXFsARBHVTTodf3uyE/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}]),
    dict(proyecto_nombre="GD El Mandarino", inversionista_nombre="LAS FAROTAS SOLAR S.A.S",
         fecha_firma_contrato="2026-02-03",
         enlace_drive="https://drive.google.com/file/d/1ogA7nVDa4muew6s1aeh3CuXJdZN8MRJE/view?usp=sharing",
         tarifa_cgm=5.5, tarifa_representacion=5.5,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":5.5,"esBase":True}]),
    dict(proyecto_nombre="GD Isabela", inversionista_nombre="JHON JAIME CASTRO CHAPARRO",
         fecha_firma_contrato="2026-02-13",
         enlace_drive="https://drive.google.com/file/d/1Bs870ApgaiXu8oX2c-7MiuH20Mx71ipk/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}]),
    dict(proyecto_nombre="GD ELEKTRA", inversionista_nombre="QUANTUM ENERGY INGENIERIA S.A.S",
         fecha_firma_contrato="2026-03-12",
         enlace_drive="https://drive.google.com/file/d/1ha7tiY1QEgU99SvgxWqxW75BAbI49Pz9/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}]),
    dict(proyecto_nombre="Agustin 2", inversionista_nombre="FONSAR S.A.S.",
         fecha_firma_contrato="2026-03-12",
         enlace_drive="https://drive.google.com/file/d/1OIO4dGe1Dqi-5fa4ZWaAE8lyUZSmiX9K/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}]),
    dict(proyecto_nombre="Agustin 3", inversionista_nombre="FONSAR S.A.S.",
         fecha_firma_contrato="2026-03-12",
         enlace_drive="https://drive.google.com/file/d/1tHc1YpqCgeKOfa77F18OxNRR0XfmWp1t/view?usp=sharing",
         tarifa_cgm=6.0, tarifa_representacion=6.0,
         indexacion_cgm=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}],
         indexacion_representacion=[{"año":2026,"ipc":None,"valor":6.0,"esBase":True}]),
    dict(proyecto_nombre="MGS 0011 El Roble",
         inversionista_nombre="PROMOTORA DE ENERGIA ELECTRICA DE CARTAGENA S.A.S E.S.P.",
         tarifa_cgm=6.0,
         indexacion_cgm=[{"año":2024,"ipc":None,"valor":6.0,"esBase":True}],
         indexacion_representacion=[]),
]


def _run_cgm_seed() -> None:
    """
    Carga y mantiene contratos CGM/Representacion.
    Idempotente: usa (inversionista + codigo_sun_factory) como clave de dedup.
    Corre en cada startup: inserta nuevos y repara proyecto_id NULL.
    """
    import re as _re
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.models.contratos import ContratoServicio

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # Mapa de proyectos para matching
        proyectos_rows = db.execute(
            text("SELECT id, nombre_comercial, codigo_tsf FROM proyectos")
        ).fetchall()
        por_nombre = {(r[1] or "").lower(): r[0] for r in proyectos_rows if r[1]}
        por_tsf    = {(r[2] or "").lower(): r[0] for r in proyectos_rows if r[2]}

        def _buscar(nombre, sf):
            # 1. Por codigo Sun Factory == codigo_tsf del proyecto
            if sf and sf.lower() in por_tsf:
                return por_tsf[sf.lower()]
            # 2. Por numero de 4 digitos (ej. "0010" de "MGS 0010 - Villanueva")
            for num in _re.findall(r'\d{4}', nombre):
                for db_n, db_id in por_nombre.items():
                    if num in db_n:
                        return db_id
            # 3. Por palabras clave largas
            clean = _re.sub(r'[-()]', ' ', nombre)
            for p in [w.lower() for w in clean.split() if len(w) > 4]:
                for db_n, db_id in por_nombre.items():
                    if p in db_n:
                        return db_id
            return None

        # ── Paso 1: insertar contratos faltantes ─────────────────────────────────
        insertados = 0
        for c in _CGM_CONTRATOS:
            nombre  = c.get("proyecto_nombre", "")
            inv     = c.get("inversionista_nombre")
            sf      = c.get("codigo_sun_factory")

            # Dedup por (inversionista + codigo_sun_factory) o (inversionista + nombre_ref)
            filtros = [
                ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.inversionista_nombre == inv,
                ContratoServicio.codigo_sun_factory == sf if sf
                    else ContratoServicio.nombre_proyecto_ref == nombre,
            ]
            ya = db.query(ContratoServicio).filter(*filtros).first()
            if ya:
                if not ya.nombre_proyecto_ref:
                    ya.nombre_proyecto_ref = nombre  # retroalimentar registros viejos
                continue

            fecha_str = c.get("fecha_firma_contrato")
            fecha = date.fromisoformat(fecha_str) if fecha_str else None

            db.add(ContratoServicio(
                proyecto_id=_buscar(nombre, sf),
                servicio_aplica="representacion",
                estado="vigente",
                inversionista_nombre=inv,
                portafolio=c.get("portafolio"),
                codigo_sun_factory=sf,
                nombre_proyecto_ref=nombre,
                tarifa_admin=c.get("tarifa_admin"),
                tarifa_cgm=c.get("tarifa_cgm"),
                tarifa_representacion=c.get("tarifa_representacion"),
                indexacion_cgm=c.get("indexacion_cgm") or [],
                indexacion_representacion=c.get("indexacion_representacion") or [],
                fecha_firma_contrato=fecha,
                enlace_drive=c.get("enlace_drive"),
            ))
            insertados += 1

        db.commit()
        if insertados:
            print(f"[cgm seed] {insertados} contratos nuevos insertados")

        # ── Paso 2: reparar proyecto_id = NULL en registros existentes ────────────
        sin_pid = db.execute(text("""
            SELECT id, codigo_sun_factory, nombre_proyecto_ref
            FROM contratos_servicio
            WHERE proyecto_id IS NULL
              AND servicio_aplica = 'representacion'
              AND inversionista_nombre IS NOT NULL
        """)).fetchall()

        reparados = 0
        for cid, sf, ref in sin_pid:
            pid = _buscar(ref or "", sf or "")
            if pid:
                db.execute(
                    text("UPDATE contratos_servicio SET proyecto_id = :pid WHERE id = :cid"),
                    {"pid": pid, "cid": cid},
                )
                reparados += 1
        db.commit()
        if reparados:
            print(f"[cgm seed] {reparados} proyecto_id reparados")

    except Exception as e:
        db.rollback()
        print(f"[cgm seed] ERROR: {e}")
    finally:
        db.close()


_mgs_scheduler = None


def _scheduled_generation_sync():
    """Sync daily generation from Solenium into generacion_diaria."""
    from datetime import date, timedelta
    if not settings.SOLENIUM_USER or not settings.SOLENIUM_PASS:
        return
    try:
        from app.services.mgs.solenium_client import SoleniumClient
        client = SoleniumClient()
        if not client.enabled:
            return

        db = None
        try:
            from app.core.database import SessionLocal
            db = SessionLocal()
            rows = db.execute(text(
                "SELECT id, project_id_solenium FROM proyectos "
                "WHERE project_id_solenium IS NOT NULL AND estado = 'en_operacion'"
            )).fetchall()
        finally:
            if db:
                db.close()

        if not rows:
            print("[gen_sync] No projects with Solenium IDs in operation")
            return

        end = date.today()
        start = end - timedelta(days=7)
        total_upserted = 0

        for proyecto_id, sol_id in rows:
            try:
                sol_id_int = int(sol_id)
            except (ValueError, TypeError):
                continue

            data = client.get_energy(
                sol_id_int,
                granularity="day",
                date_from=start.isoformat(),
                date_to=end.isoformat(),
            )
            if not data:
                continue

            raw = data.get("results") or data.get("data") or data if isinstance(data, dict) else data
            day_rows = []
            if isinstance(raw, dict):
                for k, v in raw.items():
                    kwh = None
                    if isinstance(v, (int, float)):
                        kwh = v
                    elif isinstance(v, dict) and "value" in v:
                        kwh = v["value"]
                    if kwh is not None and kwh > 0:
                        day_rows.append((k, round(kwh, 3)))
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        d = item.get("date") or item.get("day")
                        kwh = item.get("kwh") or item.get("value") or item.get("energy")
                        if d and kwh and float(kwh) > 0:
                            day_rows.append((str(d), round(float(kwh), 3)))

            if not day_rows:
                continue

            db = None
            try:
                db = SessionLocal()
                for fecha_str, kwh in day_rows:
                    db.execute(text("""
                        INSERT INTO generacion_diaria (proyecto_id, fecha, kwh_real, fuente)
                        VALUES (:pid, :fecha, :kwh, 'solenium')
                        ON CONFLICT (proyecto_id, fecha) DO UPDATE
                        SET kwh_real = EXCLUDED.kwh_real, fuente = 'solenium',
                            updated_at = NOW()
                        WHERE generacion_diaria.fuente = 'solenium'
                    """), {"pid": proyecto_id, "fecha": fecha_str, "kwh": kwh})
                db.commit()
                total_upserted += len(day_rows)
            except Exception as e:
                if db:
                    db.rollback()
                print(f"[gen_sync] DB error for project {proyecto_id}: {e}")
            finally:
                if db:
                    db.close()

        print(f"[gen_sync] Synced {total_upserted} day-rows from {len(rows)} Solenium projects")
    except Exception as e:
        print(f"[gen_sync] Failed: {e}")


def _scheduled_bolsa_ingest():
    """Daily ingest of bolsa prices from EVO energy-api."""
    import json as _json
    if not settings.EVO_API_URL:
        return
    try:
        headers = {}
        if settings.EVO_API_TOKEN:
            headers["X-EVO-Token"] = settings.EVO_API_TOKEN
        import httpx
        with httpx.Client(timeout=httpx.Timeout(10.0, read=30.0)) as client:
            resp = client.get(
                f"{settings.EVO_API_URL.rstrip('/')}/dailyspot/latest",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        fecha = data.get("date")
        if not fecha:
            print("[bolsa_ingest] No date in response")
            return
        if data.get("stale_days", 0) > 2:
            print(f"[bolsa_ingest] Skipping stale data: {fecha} ({data.get('stale_days')}d old)")
            return

        from app.api.v1.evo_proxy import _persist_dailyspot
        _persist_dailyspot(data)
        print(f"[bolsa_ingest] Persisted bolsa prices for {fecha}")
    except Exception as e:
        print(f"[bolsa_ingest] Failed: {e}")


def _scheduled_correlation_sync():
    """Daily cross-database correlation sync."""
    try:
        db = SessionLocal()
        try:
            from app.services.correlation import correlate_projects
            result = correlate_projects(db)
            print(f"[correlation_sync] OK — {result.get('correlations_updated', 0)} updated")
        except Exception as e:
            print(f"[correlation_sync] Failed: {e}")
            # Log error
            try:
                db.execute(text(
                    "INSERT INTO correlation_sync_log (synced_at, projects_processed, correlations_updated, error) "
                    "VALUES (NOW(), 0, 0, :err)"
                ), {"err": str(e)})
                db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()
    except Exception as e:
        print(f"[correlation_sync] Failed to get DB session: {e}")


def _scheduled_evo_forecast_ingest():
    """Daily ingest of climate forecast from EVO energy-api."""
    if not settings.EVO_API_URL:
        return
    try:
        headers = {}
        if settings.EVO_API_TOKEN:
            headers["X-EVO-Token"] = settings.EVO_API_TOKEN
        import httpx
        with httpx.Client(timeout=httpx.Timeout(10.0, read=30.0)) as client:
            resp = client.get(
                f"{settings.EVO_API_URL.rstrip('/')}/clima/forecast",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        from app.api.v1.evo_proxy import _persist_forecast
        _persist_forecast(data)
        print(f"[evo_forecast_ingest] Persisted forecast")
    except Exception as e:
        print(f"[evo_forecast_ingest] Failed: {e}")


_ALERTA_EMAILS = ["adhara@unergy.io", "jessica@unergy.io"]


def _scheduled_representacion_alertas():
    """
    Revisa aniversarios de contratos CGM/Representación.
    Envía email 30 y 15 días antes del aniversario a _ALERTA_EMAILS.
    Corre diariamente a las 08:00.
    """
    import json as _json
    from datetime import date, timedelta
    from pathlib import Path as _Path

    try:
        from app.services.email_service import _smtp_send, _log_send
        from app.core.config import settings as _s
        import smtplib, ssl
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        if not _s.SMTP_HOST:
            return

        data_dir = _Path(__file__).parent.parent / "data"
        raw = _json.loads((data_dir / "DataCGM.json").read_text(encoding="utf-8"))
        contratos = raw.get("Indexación", [])

        today = date.today()
        alertas_enviadas = 0

        for c in contratos:
            firma_str = c.get("Firma contrato")
            proyecto = (c.get("Proyecto") or "").strip()
            inv = (c.get("Inversionista") or "").strip()
            tarifa_cgm = c.get("Tarifa CGM (kWh)", 0) or 0
            tarifa_rep = c.get("Tarifa Representación (kWh)", 0) or 0

            if not firma_str or not proyecto:
                continue

            try:
                firma = date.fromisoformat(firma_str)
            except ValueError:
                continue

            # Calcular próximo aniversario
            base_year = firma.year
            for offset in range(1, 10):
                aniv_year = base_year + offset
                try:
                    aniv = date(aniv_year, firma.month, firma.day)
                except ValueError:
                    # Feb 29 en año no bisiesto → Feb 28
                    aniv = date(aniv_year, firma.month, 28)

                if aniv < today:
                    continue  # ya pasó

                dias_restantes = (aniv - today).days
                if dias_restantes not in (30, 15):
                    continue

                # Calcular valor indexado para ese aniversario
                # IPC dic del año anterior al aniversario
                ipc_key = aniv_year - 1  # IPC dic 2024 → aniversario 2025
                ipc_rates = {2023: 0.0928, 2024: 0.052, 2025: 0.051}
                ipc = ipc_rates.get(ipc_key, 0.051)

                # Valor del aniversario anterior * (1 + IPC)
                # Aproximación: usamos tarifa base para simplicidad
                valor_cgm_nuevo = round(tarifa_cgm * ((1 + ipc) ** offset), 4) if tarifa_cgm else None
                valor_rep_nuevo = round(tarifa_rep * ((1 + ipc) ** offset), 4) if tarifa_rep else None

                subject = (
                    f"Alerta de renovacion CGM — {proyecto} — "
                    f"{dias_restantes} dias para aniversario"
                )
                body_html = f"""
<html>
<body style="font-family:Arial,sans-serif;color:#1A0F2E;max-width:560px;margin:0 auto;padding:0">
  <div style="background:#1A0F2E;padding:24px 28px;border-radius:10px 10px 0 0">
    <div style="color:#F6FF72;font-size:20px;font-weight:800;letter-spacing:1px">UNERGY</div>
    <div style="color:#6B5F80;font-size:11px;letter-spacing:.8px;text-transform:uppercase;margin-top:2px">
      Alerta de Renovacion CGM
    </div>
  </div>
  <div style="background:#F7F4FD;padding:28px;border:1px solid #EDE8F5;border-top:none;border-radius:0 0 10px 10px">
    <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;padding:12px 16px;margin-bottom:20px">
      <strong>En {dias_restantes} dias</strong> se cumple el aniversario del contrato
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:14px">
      <tr><td style="padding:6px 0;color:#6B5F80;width:180px">Proyecto</td>
          <td style="padding:6px 0;font-weight:600">{proyecto}</td></tr>
      <tr><td style="padding:6px 0;color:#6B5F80">Inversionista</td>
          <td style="padding:6px 0;font-weight:600">{inv or "—"}</td></tr>
      <tr><td style="padding:6px 0;color:#6B5F80">Fecha aniversario</td>
          <td style="padding:6px 0;font-weight:600">{aniv.strftime("%d/%m/%Y")}</td></tr>
      <tr><td style="padding:6px 0;color:#6B5F80">IPC aplicado</td>
          <td style="padding:6px 0;font-weight:600">{ipc*100:.2f}% (IPC dic {ipc_key})</td></tr>
      {'<tr><td style="padding:6px 0;color:#6B5F80">Nueva tarifa CGM</td><td style="padding:6px 0;font-weight:600;color:#f59e0b">' + f'{valor_cgm_nuevo} $/kWh</td></tr>' if valor_cgm_nuevo else ""}
      {'<tr><td style="padding:6px 0;color:#6B5F80">Nueva tarifa Rep.</td><td style="padding:6px 0;font-weight:600;color:#3b82f6">' + f'{valor_rep_nuevo} $/kWh</td></tr>' if valor_rep_nuevo else ""}
    </table>
    <p style="color:#6B5F80;font-size:12px;margin-top:20px">
      Este es un mensaje automatico del sistema de Operaciones Unergy.<br>
      <a href="mailto:operaciones@unergy.io" style="color:#915BD8">operaciones@unergy.io</a>
    </p>
  </div>
</body>
</html>"""

                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = _s.SMTP_FROM
                msg["To"] = ", ".join(_ALERTA_EMAILS)
                msg.attach(MIMEText(body_html, "html", "utf-8"))

                try:
                    context = ssl.create_default_context()
                    with smtplib.SMTP(_s.SMTP_HOST, _s.SMTP_PORT) as server:
                        server.ehlo()
                        server.starttls(context=context)
                        server.login(_s.SMTP_USER, _s.SMTP_PASSWORD)
                        server.sendmail(_s.SMTP_FROM, _ALERTA_EMAILS, msg.as_string())
                    _log_send(
                        to_email=_ALERTA_EMAILS[0],
                        cc=_ALERTA_EMAILS[1:],
                        subject=subject,
                        tipo="alerta_cgm",
                        success=True,
                    )
                    alertas_enviadas += 1
                except Exception as exc:
                    _log_send(
                        to_email=_ALERTA_EMAILS[0],
                        cc=_ALERTA_EMAILS[1:],
                        subject=subject,
                        tipo="alerta_cgm",
                        success=False,
                        error_msg=str(exc),
                    )
                    print(f"[cgm_alertas] Error email {proyecto}: {exc}")
                break  # solo el próximo aniversario

        if alertas_enviadas:
            print(f"[cgm_alertas] {alertas_enviadas} alertas enviadas")

    except Exception as e:
        print(f"[cgm_alertas] ERROR: {e}")


_OM_IPC_SEED = [
    {"año": 2024, "tasa": 0.0928, "confirmado": True, "fuente": "DANE"},
    {"año": 2025, "tasa": 0.0520, "confirmado": True, "fuente": "DANE"},
    {"año": 2026, "tasa": 0.0510, "confirmado": True, "fuente": "DANE"},
]

_OM_PROYECTOS_SEED = [
    {"nombre": "Minigranja Solar Uruaco",            "fecha_inicio": "2023-06-17", "valor_base_anual": 25880000},
    {"nombre": "Minigranja Solar Baraya",             "fecha_inicio": "2024-02-17", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Cañahuate",          "fecha_inicio": "2024-02-19", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Gandalf",            "fecha_inicio": "2024-02-19", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Paz Vallenata",   "fecha_inicio": "2024-08-16", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Perijá",             "fecha_inicio": "2024-09-15", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Molino",          "fecha_inicio": "2024-09-20", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Paz Verso",       "fecha_inicio": "2024-12-05", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Esmeralda",          "fecha_inicio": "2025-02-14", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Son",             "fecha_inicio": "2025-02-16", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Puya",            "fecha_inicio": "2025-02-19", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Villanueva",         "fecha_inicio": "2025-04-04", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Merengue",           "fecha_inicio": "2026-03-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar La Reserva",         "fecha_inicio": "2025-04-25", "valor_base_anual": 48000000},
    {"nombre": "Nestlé",                              "fecha_inicio": "2025-06-26", "valor_base_anual": 78000000},
    {"nombre": "Minigranja Solar Ibirico",            "fecha_inicio": "2025-07-08", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Olimpo",          "fecha_inicio": "2025-07-20", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Mesa",            "fecha_inicio": "2025-09-12", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar San Diego Sur",      "fecha_inicio": "2026-03-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Valencia Oriente 1", "fecha_inicio": "2026-03-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar La Cacica",          "fecha_inicio": "2026-01-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Las Piloneras",      "fecha_inicio": "2026-01-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Valencia Oriente 2", "fecha_inicio": "2026-03-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Cumbia",             "fecha_inicio": "2025-01-01", "valor_base_anual": None},
    {"nombre": "Minigranja Solar Copey",              "fecha_inicio": "2025-01-01", "valor_base_anual": None},
    {"nombre": "Minigranja Solar Chiriguana 2",       "fecha_inicio": "2026-03-14", "valor_base_anual": None},
    {"nombre": "Minigranja Solar Chiriguana 4",       "fecha_inicio": "2026-03-17", "valor_base_anual": None},
]


def _run_om_seed() -> None:
    """
    Siembra datos iniciales de O&M: tasas IPC y contratos de mantenimiento.
    Idempotente — no duplica si ya existen.
    """
    import re as _re
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.models.om import IPCTasa
    from app.models.contratos import ContratoServicio

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # ── IPC seed ──────────────────────────────────────────────────────────
        for item in _OM_IPC_SEED:
            existing = db.query(IPCTasa).filter(IPCTasa.año == item["año"]).first()
            if not existing:
                db.add(IPCTasa(**item))
        db.commit()

        # ── Contratos mantenimiento seed ──────────────────────────────────────
        proyectos_db = db.execute(
            text("SELECT id, nombre_comercial FROM proyectos WHERE deleted_at IS NULL")
        ).fetchall()
        por_nombre = {(r[1] or "").lower(): r[0] for r in proyectos_db}

        def _match(nombre: str):
            n = nombre.lower()
            if n in por_nombre:
                return por_nombre[n]
            for num in _re.findall(r"\d{4}", nombre):
                for db_n, db_id in por_nombre.items():
                    if num in db_n:
                        return db_id
            partes = [w.lower() for w in _re.sub(r"[-()]", " ", nombre).split() if len(w) > 4]
            for p in partes:
                for db_n, db_id in por_nombre.items():
                    if p in db_n:
                        return db_id
            return None

        insertados = 0
        for item in _OM_PROYECTOS_SEED:
            proyecto_id = _match(item["nombre"])
            ya = None
            if proyecto_id:
                ya = db.query(ContratoServicio).filter(
                    ContratoServicio.proyecto_id == proyecto_id,
                    ContratoServicio.servicio_aplica == "mantenimiento",
                ).first()
            if not ya:
                ya = db.query(ContratoServicio).filter(
                    ContratoServicio.servicio_aplica == "mantenimiento",
                    ContratoServicio.prestador_nombre == item["nombre"],
                ).first()

            if ya:
                if not ya.tarifa_base and item["valor_base_anual"]:
                    ya.tarifa_base = item["valor_base_anual"]
                if not ya.fecha_inicio and item["fecha_inicio"]:
                    ya.fecha_inicio = date.fromisoformat(item["fecha_inicio"])
                continue

            fecha = date.fromisoformat(item["fecha_inicio"]) if item["fecha_inicio"] else None
            db.add(ContratoServicio(
                proyecto_id=proyecto_id,
                servicio_aplica="mantenimiento",
                estado="vigente",
                tarifa_base=item["valor_base_anual"],
                fecha_inicio=fecha,
                prestador_nombre=item["nombre"],
                contratante_nombre="Unergy Energía Digital S.A.S. E.S.P.",
            ))
            insertados += 1

        db.commit()
        if insertados:
            print(f"[om_seed] {insertados} contratos mantenimiento insertados")

    except Exception as e:
        db.rollback()
        print(f"[om_seed] ERROR: {e}")
    finally:
        db.close()


def _scheduled_om_ipc_check():
    """
    Corre cada 1 de enero a las 09:00.
    Verifica si falta la tasa IPC del año actual.
    Si falta, crea un registro pendiente de confirmación.
    """
    from datetime import datetime
    from sqlalchemy.orm import sessionmaker
    from app.models.om import IPCTasa

    año_actual = datetime.now().year
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        ya_existe = db.query(IPCTasa).filter(IPCTasa.año == año_actual).first()
        if not ya_existe:
            db.add(IPCTasa(
                año=año_actual,
                tasa=0.0,
                confirmado=False,
                fuente="pendiente_confirmacion",
            ))
            db.commit()
            print(f"[om_ipc_check] Tasa IPC {año_actual} pendiente de confirmación creada")
    except Exception as e:
        db.rollback()
        print(f"[om_ipc_check] ERROR: {e}")
    finally:
        db.close()


def _deferred_init():
    """Heavy initialization that runs in a background thread after the server is ready."""
    import time as _t
    _t0 = _t.time()
    global _mgs_scheduler

    for label, fn in [
        ("create_tables", _run_create_tables),
        ("column_migrations", _run_column_migrations),
        ("catalog_seed", _run_catalog_seed),
        ("tipo_migration", _run_tipo_migration),
        ("srv_operacion_sync", _run_srv_operacion_sync),
        ("cgm_seed", _run_cgm_seed),
        ("om_seed", _run_om_seed),
    ]:
        try:
            fn()
            print(f"[startup] {label} OK ({_t.time() - _t0:.1f}s)")
        except Exception as e:
            print(f"[startup] {label} FAILED: {e}")

    try:
        from app.services.audit import init_audit
        init_audit()
    except Exception as e:
        print(f"[startup] audit init FAILED: {e}")

    if settings.MGS_ENABLED:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from app.services.mgs.scheduler import poll_once, poll_once_async

            _mgs_scheduler = BackgroundScheduler(
                timezone=settings.TIMEZONE,
            )
            _mgs_scheduler.add_job(
                poll_once,
                IntervalTrigger(minutes=settings.MGS_POLL_INTERVAL_MINUTES),
                id="mgs_poll",
                name="MGS alarm poll",
            )
            from apscheduler.triggers.cron import CronTrigger

            if settings.SOLENIUM_USER:
                _mgs_scheduler.add_job(
                    _scheduled_generation_sync,
                    CronTrigger(hour=7, minute=0, timezone=settings.TIMEZONE),
                    id="gen_sync_am",
                    name="Solenium generation sync (AM)",
                )
                _mgs_scheduler.add_job(
                    _scheduled_generation_sync,
                    CronTrigger(hour=19, minute=0, timezone=settings.TIMEZONE),
                    id="gen_sync_pm",
                    name="Solenium generation sync (PM)",
                )

            if settings.EVO_API_URL:
                _mgs_scheduler.add_job(
                    _scheduled_bolsa_ingest,
                    CronTrigger(hour=11, minute=0, timezone=settings.TIMEZONE),
                    id="bolsa_ingest",
                    name="Daily bolsa price ingest",
                )
                _mgs_scheduler.add_job(
                    _scheduled_evo_forecast_ingest,
                    CronTrigger(hour=6, minute=0, timezone=settings.TIMEZONE),
                    id="evo_forecast_ingest",
                    name="Daily EVO forecast ingest",
                )

            _mgs_scheduler.add_job(
                _scheduled_correlation_sync,
                CronTrigger(hour=2, minute=0, timezone=settings.TIMEZONE),
                id="correlation_sync",
                name="Daily correlation sync",
            )

            _mgs_scheduler.add_job(
                _scheduled_representacion_alertas,
                CronTrigger(hour=8, minute=0, timezone=settings.TIMEZONE),
                id="cgm_alertas",
                name="Alertas renovacion CGM/Representacion",
            )

            _mgs_scheduler.add_job(
                _scheduled_om_ipc_check,
                CronTrigger(month=1, day=1, hour=9, minute=0, timezone=settings.TIMEZONE),
                id="om_ipc_check",
                name="Check IPC anual O&M",
            )

            _mgs_scheduler.start()
            poll_once_async()
            print(f"[startup] MGS scheduler started ({_t.time() - _t0:.1f}s)")
        except Exception as e:
            print(f"[startup] MGS scheduler FAILED: {e}")

    print(f"[startup] deferred init complete ({_t.time() - _t0:.1f}s)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from threading import Thread
    init_thread = Thread(target=_deferred_init, daemon=True)
    init_thread.start()
    print("[startup] server ready — DB init running in background")

    yield

    if _mgs_scheduler:
        _mgs_scheduler.shutdown(wait=False)
        print("[shutdown] MGS scheduler stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.1.0",  # informes pipeline + filtros fecha
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# El monitoreo se sirve desde Railway pero se embebe como iframe en la plataforma
# (Vercel u otro dominio). El origen puede ser *.vercel.app, *.unergy.io, un
# dominio custom o localhost. Usamos allow_origin_regex=r"https://.*" para
# aceptar cualquier origen HTTPS sin hardcodear dominios.
# Seguridad: la API usa JWT en el header Authorization (no cookies), por lo que
# ampliar CORS no introduce vulnerabilidades CSRF.
_ALLOWED_ORIGINS = [
    settings.FRONTEND_URL,
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*",   # cualquier origen HTTPS (seguro con JWT)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# ── archivos estáticos uploads ────────────────────────────────────────────────
_uploads_path = Path("uploads")
_uploads_path.mkdir(exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(_uploads_path)), name="uploads")

# ── monitoreo: servir fallas-unergy como SPA ─────────────────────────────────
_monitoreo_path = Path("static/monitoreo")
_monitoreo_path.mkdir(parents=True, exist_ok=True)

_monitoreo_index = _monitoreo_path / "index.html"


@app.get("/monitoreo", include_in_schema=False)
@app.get("/monitoreo/", include_in_schema=False)
async def serve_monitoreo():
    if _monitoreo_index.exists():
        return FileResponse(str(_monitoreo_index), media_type="text/html")
    return {"error": "Monitoreo no desplegado aún. Ejecuta scripts/patch_monitoreo.py"}


if _monitoreo_path.exists() and any(_monitoreo_path.iterdir()):
    app.mount("/monitoreo/static", StaticFiles(directory=str(_monitoreo_path)), name="monitoreo_static")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
