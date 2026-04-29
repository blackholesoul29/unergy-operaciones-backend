from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
]


def _run_column_migrations() -> None:
    for stmt in _PENDING_DDLS:
        try:
            with engine.connect() as conn:
                conn.execute(text(stmt))
                conn.commit()
        except Exception as e:
            print(f"[startup migration skipped] {e}")


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_column_migrations()
    _run_catalog_seed()
    yield


app = FastAPI(title=settings.APP_NAME, version="1.0.0", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Servir archivos subidos (uploads/)
_uploads_path = Path("uploads")
_uploads_path.mkdir(exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(_uploads_path)), name="uploads")

# Servir la app de monitoreo (fallas-unergy adaptado)
_monitoreo_index = Path("static/monitoreo/index.html")


@app.get("/monitoreo", include_in_schema=False)
@app.get("/monitoreo/", include_in_schema=False)
async def serve_monitoreo():
    if _monitoreo_index.exists():
        return FileResponse(str(_monitoreo_index), media_type="text/html")
    return {"error": "Monitoreo no desplegado"}


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
