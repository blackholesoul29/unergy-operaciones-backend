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
    "ALTER TABLE liquidacion_costos ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS nro_soporte VARCHAR(100)",
    "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
    "ALTER TABLE liquidacion_mandato_lineas ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
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
]


def _run_column_migrations() -> None:
    add_value_stmts = [s for s in _PENDING_DDLS if "ADD VALUE" in s.upper()]
    regular_stmts = [s for s in _PENDING_DDLS if "ADD VALUE" not in s.upper()]

    # Batch regular DDLs in a single connection (much faster than 200+ connections)
    if regular_stmts:
        with engine.connect() as conn:
            for stmt in regular_stmts:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"[startup ddl skipped] {e}")

    # ALTER TYPE … ADD VALUE cannot run inside a transaction block in PostgreSQL
    for stmt in add_value_stmts:
        try:
            with engine.connect() as conn:
                conn.execute(text("COMMIT"))
                conn.execute(text(stmt))
        except Exception as e:
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
    version="1.0.0",
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
