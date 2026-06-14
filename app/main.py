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
    """Create any missing base tables (idempotent — skips existing tables).

    La evolución del esquema (columnas, enums, índices, constraints) la gestiona
    Alembic; ``create_all`` solo asegura las tablas base que aún no existan.
    Las migraciones se aplican aparte vía ``alembic upgrade head`` (start.sh).
    """
    try:
        from app.models import Base
        Base.metadata.create_all(bind=engine)
        print("[startup] Tables ensured OK")
    except Exception as e:
        print(f"[startup] create_all skipped: {e}")


# Datos iniciales de contratos CGM/Representación — fuente: Data/contratosCGM.json
_CGM_CONTRATOS = [
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
    """Carga inicial de contratos CGM/Representación. Idempotente — omite los que ya existen."""
    import json as _json
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.models.contratos import ContratoServicio

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        ya_existen = db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "representacion",
            ContratoServicio.inversionista_nombre.isnot(None),
        ).count()

        if ya_existen >= len(_CGM_CONTRATOS):
            print(f"[cgm seed] ya existen {ya_existen} contratos — omitiendo")
            return

        insertados = 0
        for c in _CGM_CONTRATOS:
            nombre = c.get("proyecto_nombre", "")
            inv = c.get("inversionista_nombre")

            ya = db.query(ContratoServicio).filter(
                ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.inversionista_nombre == inv,
            ).first()
            if ya:
                continue

            fecha_str = c.get("fecha_firma_contrato")
            fecha = date.fromisoformat(fecha_str) if fecha_str else None

            proyecto = db.execute(
                text("SELECT id FROM proyectos WHERE LOWER(nombre_comercial) LIKE LOWER(:q) LIMIT 1"),
                {"q": f"%{nombre.split(' - ')[-1].strip()[:20]}%"},
            ).first()

            obj = ContratoServicio(
                proyecto_id=proyecto[0] if proyecto else None,
                servicio_aplica="representacion",
                contratante_nombre="Unergy Energia Digital S.A.S. E.S.P.",
                prestador_nombre="Unergy Energia Digital S.A.S. E.S.P.",
                estado="vigente",
                inversionista_nombre=inv,
                portafolio=c.get("portafolio"),
                codigo_sun_factory=c.get("codigo_sun_factory"),
                tarifa_admin=c.get("tarifa_admin"),
                tarifa_cgm=c.get("tarifa_cgm"),
                tarifa_representacion=c.get("tarifa_representacion"),
                indexacion_cgm=c.get("indexacion_cgm") or [],
                indexacion_representacion=c.get("indexacion_representacion") or [],
                fecha_firma_contrato=fecha,
                enlace_drive=c.get("enlace_drive"),
            )
            db.add(obj)
            insertados += 1

        db.commit()
        print(f"[cgm seed] {insertados} contratos insertados")
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


def _deferred_init():
    """Heavy initialization that runs in a background thread after the server is ready."""
    import time as _t
    _t0 = _t.time()
    global _mgs_scheduler

    for label, fn in [
        ("create_tables", _run_create_tables),
        ("catalog_seed", _run_catalog_seed),
        ("tipo_migration", _run_tipo_migration),
        ("srv_operacion_sync", _run_srv_operacion_sync),
        ("cgm_seed", _run_cgm_seed),
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
