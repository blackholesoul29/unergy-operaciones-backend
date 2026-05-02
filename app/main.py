from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine
from app.api.v1.router import api_router

# Idempotent DDL run at startup — safe to run on every boot
_PENDING_DDLS = [
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS codigo_legado VARCHAR(30)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_fallas_codigo_legado_unique ON fallas (codigo_legado) WHERE codigo_legado IS NOT NULL",
    # migration 003 — monitoreo fields
    "ALTER TABLE fallas ADD COLUMN IF NOT EXISTS fotos_urls TEXT",
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
<<<<<<< Updated upstream
    # migration 004 — P50/P90 monthly simulation per project (JSON arrays of 12 values)
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS p90_mensual_kwh TEXT",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS p50_mensual_kwh TEXT",
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
        archivos_json TEXT,
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
    "ALTER TABLE proyectos ALTER COLUMN cliente_id DROP NOT NULL",
    # enum values for liquidaciones
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'despacho'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'ventas_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'compras_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'redistribucion_ingresos'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
    "ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
]


def _run_column_migrations() -> None:
    for stmt in _PENDING_DDLS:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_create_tables()
    _run_column_migrations()
    _run_catalog_seed()
    _run_tipo_migration()
    _run_srv_operacion_sync()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# El iframe de monitoreo se sirve desde Railway, por eso su origen no viene
# del Vercel frontend; las peticiones API son same-origin. Solo necesitamos
# permitir el Vercel frontend para las demás rutas.
_ALLOWED_ORIGINS = [
    settings.FRONTEND_URL,
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
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


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
