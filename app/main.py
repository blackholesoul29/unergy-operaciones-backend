import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, SessionLocal
from app.api.v1.router import api_router

# El proyecto nunca configuró logging.basicConfig() en ningún lado -- sin
# eso, el root logger no tiene handler propio, y Python cae a
# `logging.lastResort` (un StreamHandler a stderr, pero SOLO a partir de
# WARNING). Resultado real: todo logger.info()/logger.debug() de CUALQUIER
# módulo del backend (no solo este archivo) queda invisible en los logs de
# Railway, indistinguible de "no corrió" -- así se investigó en vano por
# qué el Excel de Cedillanos no se cargó un día (2026-08-27): el job había
# corrido bien sus 9 intentos, cada uno logueando "sin correos nuevos" a
# INFO, pero ninguna de esas líneas llegó a verse. Con esto, cualquier
# logger.info() del proyecto queda visible sin tener que ir a buscar el
# dato directo en la base de datos.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Idempotent DDL run at startup — safe to run on every boot
# _PENDING_DDLS vivio aca: 468 sentencias DDL que corrian en CADA arranque,
# cada una envuelta en un try/except que imprimia "[startup ddl skipped]".
# Retirada el 2026-08-31. Por que:
#   * No tenia control de version: reejecutaba las 468 en cada boot y todo lo
#     ya aplicado respondia DuplicateObject. Los 6 ALTER TYPE ... RENAME VALUE
#     eran de un solo uso y fallaban para siempre.
#   * La tolerancia escondia fallos reales: el backfill de proyectos.altitud_msnm
#     llevaba meses reventando sin que nadie se enterara.
#   * Corria ANTES que Alembic y creaba objetos que hacian fallar revisiones
#     (incidente de la migracion 131, 2026-08-31).
# Antes de borrarla se verifico contra la base que no le quedaba nada por hacer:
# 0 columnas y 0 tablas del modelo ausentes. El DDL sigue en la historia de git
# (`git show HEAD~1:app/main.py`) y en el esquema vivo.
# Desde ahora: el esquema se cambia SOLO con una revision de Alembic.


# _BACKFILLS_REFERENCIA / _run_backfills_referencia() vivieron acá: backfill
# hardcodeado de fronteras.quoia_meter_id (mapeo FRT -> id de medidor en
# Quoia, ver hallazgo F12 de esquema-bd-produccion/DEPURACION.md). La columna
# se dropeó el 2026-07-22 -- el mapeo lo reemplazó FRONTERA_NODE_MAP
# (app/services/mgs/gaia_client.py), que ya no depende de una columna propia.
# Retirado 2026-08-26 (auditoría de _PENDING_DDLS): las 28 sentencias
# fallaban en silencio en CADA arranque desde entonces (columna inexistente),
# sin ningún efecto real -- confirmado en producción antes de borrar.


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


# Semilla del mapeo sitio Starlink → minigranja. patron (normalizado como queda en
# agrupado.descripcion) → nombre_comercial del proyecto. Migrado del hardcode
# STARLINK_TO_PANEL del frontend. NESTLE / OFICINA UNERGY no son minigranjas → NULL.
_STARLINK_SEED = {
    "BARAYA": "Minigranja Solar Baraya",
    "CUMBIA": "Minigranja Solar Cumbia",
    "EL COPEY OCCIDENTE": "Minigranja Solar Copey",
    "EL MOLINO": "Minigranja Solar El Molino",
    "EL OLIMPO": "Minigranja Solar El Olimpo",
    "EL SON": "Minigranja Solar El Son",
    "GANDALF": "Minigranja Solar Gandalf",
    "CANAHUATE": "Minigranja Solar Cañahuate",
    "IBIRICO": "Minigranja Solar Ibirico",
    "MAPALE": "Minigranja Solar Mapalé",
    "LA ESMERALDA": "Minigranja Solar Esmeralda",
    "LA MESA": "Minigranja Solar La Mesa",
    "VALLENATA": "Minigranja Solar La Paz Vallenata",
    "LEYENDA": "Minigranja Solar La Paz Leyenda",
    "LA RESERVA": "MGS 0012 La Reserva",
    "PUYA": "Minigranja Solar La Puya",
    "MGS LA PAZ VERSO": "Minigranja Solar La Paz Verso",
    "PERUA": "Minigranja Solar Perijá",
    "SAN DIEGO SUR": "Minigranja Solar San Diego Sur",
    "URUACO": "Minigranja Solar Uruaco",
    "VILLANUEVA": "Minigranja Solar Villanueva",
    "CACICA": "Minigranja Solar La Cacica",
    "PILONERAS": "Minigranja Solar Las Piloneras",
    "VALENCIA 1": "Minigranja Solar Valencia Oriente 1",
    "VALENCIA 2": "Minigranja Solar Valencia Oriente 2",
    "CHIRIGUANA N2": "Minigranja Solar Chiriguana 2",
    "CHIRIGUANA N4": "Minigranja Solar Chiriguana 4",
    # Nombres individuales que produce el parser al dividir splits y que no están en
    # el mapa del front (JOROPO MAPALE → Joropo/Mapale; PUYA Y MERENGUE → Puya/Merengue):
    "JOROPO": "Minigranja Solar Joropo",
    "MERENGUE": "MGS 0019 El Merengue",
    # Sitios conocidos que NO son minigranjas → proyecto_id NULL (quedan "sin asignar"):
    "NESTLE": None,
    "OFICINA UNERGY": None,
}


def _run_starlink_mapeo_seed() -> None:
    """Siembra starlink_mapeo_sitio (idempotente: no pisa proyecto_id editado) y
    hace backfill de starlink_factura_linea para las facturas ya guardadas."""
    from sqlalchemy.orm import sessionmaker
    from app.models.proyectos import Proyecto
    from app.models.starlink import StarlinkFactura, StarlinkMapeoSitio, StarlinkFacturaLinea
    from app.api.v1.starlink import _regenerar_lineas

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        proyectos = {p.nombre_comercial: p.id for p in db.query(Proyecto.id, Proyecto.nombre_comercial).all()}
        for patron, nombre in _STARLINK_SEED.items():
            patron = patron.strip()
            if not patron:
                continue
            existente = db.query(StarlinkMapeoSitio).filter(StarlinkMapeoSitio.patron == patron).first()
            if existente:
                continue  # idempotente: no tocar lo que ya existe (posible edición manual)
            db.add(StarlinkMapeoSitio(
                patron=patron,
                proyecto_id=proyectos.get(nombre) if nombre else None,
                activo=True,
            ))
        db.flush()

        for fac in db.query(StarlinkFactura).all():
            tiene = db.query(StarlinkFacturaLinea).filter(StarlinkFacturaLinea.factura_id == fac.id).first()
            if not tiene:
                _regenerar_lineas(db, fac)
        db.commit()
        print("[starlink seed] OK — mapeo sembrado y backfill de líneas")
    except Exception as e:
        db.rollback()
        print(f"[starlink seed] ERROR: {e}")
    finally:
        db.close()


def _run_estructura_fallas_seed() -> None:
    """Siembra (idempotente) las categorías/tipos del reporte estructurado a partir
    de ESTRUCTURA_FALLAS. Permite que las vistas/analytics legacy (que muestran
    falla.tipo.etiqueta) sigan funcionando con las fallas nuevas. tipo.codigo =
    "{categoria}.{subtipo}". No borra ni toca el catálogo legacy."""
    from sqlalchemy.orm import sessionmaker
    from app.models.fallas import FallaCatCategoria, FallaCatTipo
    from app.services.fallas.estructura import ESTRUCTURA_FALLAS, tipo_codigo

    try:
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            for idx, cat in enumerate(ESTRUCTURA_FALLAS):
                cat_obj = db.query(FallaCatCategoria).filter_by(codigo=cat["codigo"]).first()
                if cat_obj:
                    cat_obj.etiqueta = cat["etiqueta"]
                    cat_obj.icono = cat.get("icono")
                    cat_obj.color_hex = cat.get("color_hex")
                    cat_obj.orden = 100 + idx  # detrás del catálogo legacy
                    cat_obj.activa = True
                else:
                    cat_obj = FallaCatCategoria(
                        codigo=cat["codigo"], etiqueta=cat["etiqueta"],
                        icono=cat.get("icono"), color_hex=cat.get("color_hex"),
                        orden=100 + idx, activa=True,
                    )
                    db.add(cat_obj)
                    db.flush()
                # opciones (red/frontera/eventos) y tipos_falla (inversores)
                subitems = list(cat.get("opciones", [])) + list(cat.get("tipos_falla", []))
                for sub in subitems:
                    code = tipo_codigo(cat["codigo"], sub["codigo"])
                    tipo_obj = db.query(FallaCatTipo).filter_by(codigo=code).first()
                    if tipo_obj:
                        tipo_obj.etiqueta = sub["etiqueta"]
                        tipo_obj.categoria_id = cat_obj.id
                        tipo_obj.activa = True
                    else:
                        db.add(FallaCatTipo(
                            categoria_id=cat_obj.id, codigo=code,
                            etiqueta=sub["etiqueta"], descripcion=sub.get("descripcion"),
                            activa=True,
                        ))
            # Desactivar tipos de inversores retirados de la estructura: dejan de
            # ofrecerse, pero se conserva la fila (no se borra) para no romper
            # fallas históricas que aún referencian ese tipo_id.
            inv_cat = next((c for c in ESTRUCTURA_FALLAS if c["codigo"] == "inversores"), None)
            if inv_cat:
                vigentes = {tipo_codigo("inversores", t["codigo"]) for t in inv_cat.get("tipos_falla", [])}
                obsoletos = (
                    db.query(FallaCatTipo)
                    .filter(FallaCatTipo.codigo.like("inversores.%"),
                            FallaCatTipo.codigo.notin_(vigentes),
                            FallaCatTipo.activa == True)
                    .all()
                )
                for t in obsoletos:
                    t.activa = False
                if obsoletos:
                    print(f"[estructura fallas seed] {len(obsoletos)} tipo(s) de inversores desactivados")
            db.commit()
            print("[estructura fallas seed] OK")
        except Exception as e:
            db.rollback()
            print(f"[estructura fallas seed] ERROR: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[estructura fallas seed] skipped: {e}")


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


_NUMERICO = re.compile(r"^\d+\.\d+$")


def es_tipo_legacy(codigo: str | None, estructurados: set[str]) -> bool:
    """¿Este `FallaCatTipo.codigo` es de la taxonomia vieja, la snake_case?

    En `fallas_cat_tipos` conviven TRES generaciones de codigos:

        "corte_energia"      -> legacy de verdad; esto tiene que migrarse
        "2.1"                -> numerico; es el destino de la migracion
        "red.baja_tension"   -> estructurado (D-11); NO se toca

    Hasta el 2026-08-27 la regla era "legacy = no numerico", y eso se comia al
    catalogo estructurado entero: `tipo_migration` re-apuntaba 5.086 fallas a un
    tipo numerico de respaldo en CADA arranque, y `fallas_tipo_backfill` -- que
    corre despues -- las devolvia. 23 arranques en 16 horas, con la base
    sirviendo el dato equivocado en la ventana entre las dos tareas.

    Por eso los estructurados se excluyen preguntandole a la estructura, no
    mirando la forma del codigo: agregar una categoria no puede volver a
    reabrir esto.
    """
    if not codigo:
        return False
    if _NUMERICO.match(codigo):
        return False
    return codigo not in estructurados


def _run_tipo_migration() -> None:
    """Re-point faults that use old snake_case tipo codes to the new numeric ones."""
    from sqlalchemy.orm import sessionmaker, joinedload
    from app.models.fallas import Falla, FallaCatTipo
    from app.services.fallas.estructura import codigos_estructurados

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        estructurados = codigos_estructurados()

        new_tipos: dict[str, int] = {
            t.codigo: t.id
            for t in db.query(FallaCatTipo).filter(FallaCatTipo.activa == True).all()
            if _NUMERICO.match(t.codigo or "")
        }
        if not new_tipos:
            print("[tipo migration] No new numeric tipos found — run catalog seed first")
            return

        old_tipos = (
            db.query(FallaCatTipo)
            .options(joinedload(FallaCatTipo.categoria))
            .all()
        )
        old_tipos = [t for t in old_tipos if es_tipo_legacy(t.codigo, estructurados)]

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


# _run_srv_operacion_sync() vivió acá -- eliminada 2026-09-01 (bug real,
# reportado en producción). Corría en CADA arranque del servidor, no una
# sola vez pese al docstring ("idempotente"): forzaba srv_operacion=TRUE
# para toda minigranja/autoconsumo en operación que lo tuviera en
# False/NULL, sin ninguna excepción -- pisando en silencio cualquier
# desactivación manual hecha vía PATCH /proyectos/{id}/servicios (ver
# `allowed` en app/api/v1/proyectos.py::toggle_servicios, que expone
# srv_operacion justamente para editarlo a mano). Caso real: un proyecto
# (Bayunca) al que se le quitó el servicio manualmente volvió a aparecer
# con servicio al reiniciar el contenedor. Era un backfill de una sola vez
# (poblar el campo cuando se creó la columna) que quedó enganchado a la
# lista de tareas de arranque en vez de correr una única vez y retirarse.


def _run_mandatos_maestra_seed() -> None:
    """Siembra la maestra de mandatos. Datos, no esquema.

    Antes esta tarea tambien hacia `Base.metadata.create_all()`. Se quito el
    2026-08-31 junto con _PENDING_DDLS e init_db.py: el esquema lo crea Alembic
    y nada mas, y `scripts/verificar_esquema.py` falla el deploy si la base no
    trae lo que el modelo declara.
    """
    try:
        from app.seeds.mandatos_seed import ensure_maestra
        ensure_maestra()
    except Exception as e:
        print(f"[startup] ensure_maestra skipped: {e}")


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

    # ── Ayura 1: inversionistas que solo estaban en data/DataCGM.json ────────
    # Migrados al repo al eliminar esos JSON. Mismo portafolio, tarifas y firma
    # que los demas contratos de Ayura 1: cambia el inversionista.
    dict(proyecto_nombre="MiniGranja 0001 - Uruaco", codigo_sun_factory="COLATLT14P2",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0001 - Uruaco", codigo_sun_factory="COLATLT14P2",
         portafolio="Ayura 1", inversionista_nombre="SUNO ACTIVOS SOSTENIBLES S.A.S.",
         tarifa_admin=0.038,
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0001 - Uruaco", codigo_sun_factory="COLATLT14P2",
         portafolio="Ayura 1", inversionista_nombre="RODRIGUEZ VELEZ BEATRIZ",
         tarifa_admin=0.038,
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0004 - Valle de Gandalf", codigo_sun_factory="COLCEST61P3",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0005 - Canahuate", codigo_sun_factory="COLCEST61P1",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0006 - Perija", codigo_sun_factory="COLCEST58P2",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0007 - La Paz Vallenata", codigo_sun_factory="COLCEST9P1",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0008 - La Paz Verso", codigo_sun_factory="COLCEST2P3",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0009 - El Molino", codigo_sun_factory="COLLAGT19P2",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0010 - Villanueva", codigo_sun_factory="COLLAGT27P2",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0013 - La Mesa", codigo_sun_factory="COLSANT10P1",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0014 - El Olimpo", codigo_sun_factory="COLSANT4P2",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="Minigranja 0016 - La Puya", codigo_sun_factory="COLCEST45P5",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
    dict(proyecto_nombre="MiniGranja 0017 - La Paz Esmeralda", codigo_sun_factory="COLCEST17P1",
         portafolio="Ayura 1", inversionista_nombre="PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",
         tarifa_admin=0.038, fecha_firma_contrato="2024-10-11",
         enlace_drive=_SOPORTE_AYURA1, tarifa_cgm=5.0, tarifa_representacion=5.0,
         indexacion_cgm=_IDX_AYURA1, indexacion_representacion=_IDX_AYURA1),
]


def _cgm_norm(s: str | None) -> str:
    """Normaliza un nombre para comparar: sin tildes, sin puntuacion, sin dobles
    espacios, en mayusculas.

    El dedup del seed comparaba strings exactos y los dos seeds escriben el mismo
    inversionista de dos formas ("SOMOS BOGOTA USME SAS" vs "SOMOS BOGOTÁ USME
    SAS", "Ayura" vs "Ayurá", "FEM ENERGIA" vs "FEM ENERGÍA"): cada variante
    creaba un contrato duplicado en produccion.
    """
    import re as _re
    import unicodedata as _ud

    s = _ud.normalize("NFKD", s or "")
    s = "".join(c for c in s if not _ud.combining(c))
    return _re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def _cgm_buscar_proyecto(nombre: str, sf: str | None,
                         por_nombre: dict, por_tsf: dict) -> int | None:
    """Resuelve a que planta pertenece un contrato del seed CGM.

    Tres criterios, ninguno de los cuales adivina:
      1. codigo Sun Factory == codigo_tsf del proyecto.
      2. nombre de referencia == nombre de la planta, normalizados (exacto).
      3. el numero de 4 digitos del nombre (ej. "0010" de "MGS 0010 - Villanueva"),
         y solo si aparece en UNA sola planta.

    Antes habia un cuarto criterio que tomaba la primera palabra de mas de 4
    letras del nombre y devolvia el PRIMER proyecto que la contuviera como
    substring. Acertaba cuando el nombre del contrato ya era el de la planta
    (para eso esta ahora el criterio 2, que no depende del orden de la consulta),
    pero tambien metia contratos en plantas ajenas: "GD Yuan Solar" caia en
    "Minigranja Solar Baraya" por la palabra "solar", y con nombres de planta sin
    numero era el criterio que decidia casi todos. Un contrato sin planta es un
    pendiente visible que se resuelve a mano en Servicios > Representacion; un
    contrato en la planta equivocada es un dato falso que nadie detecta.
    """
    import re as _re

    if sf:
        pid = por_tsf.get(_cgm_norm(sf))
        if pid is not None:
            return pid

    pid = por_nombre.get(_cgm_norm(nombre))
    if pid is not None:
        return pid

    for num in _re.findall(r"\d{4}", nombre or ""):
        # Coincidencia unica: si el numero aparece en dos plantas no hay forma de
        # saber cual es, y elegir la primera es arbitrario.
        candidatos = {pid for db_n, pid in por_nombre.items() if num in db_n}
        if len(candidatos) == 1:
            return candidatos.pop()

    return None


class _CgmIndice:
    """Indice de los contratos de representacion ya existentes, para decidir si
    una entrada del seed ya esta en la base.

    Tres entradas al mismo registro, porque cada fuente historica dejo una pista
    distinta:
      - por codigo Sun Factory : lo que sembro el seed de arranque.
      - por nombre de referencia: idem, cuando el contrato no trae codigo.
      - por proyecto_id        : lo que sembro scripts/seed_contratos_cgm.py, que
        hace `c.pop("proyecto_nombre")` y nunca guarda nombre_proyecto_ref. Sin
        esta entrada, los 34 contratos sin codigo Sun Factory eran invisibles al
        dedup y se duplicaban.

    Los contratos sin inversionista quedan FUERA del indice a proposito: son los
    creados a mano en el wizard, y emparejarlos con una entrada del seed exigiria
    adivinar (una planta puede tener varios inversionistas). Se revisan a mano en
    Servicios > Representacion.
    """

    def __init__(self):
        self.por_sf, self.por_ref, self.por_pid = {}, {}, {}

    def indexar(self, reg) -> None:
        inv_n = _cgm_norm(reg.inversionista_nombre)
        if not inv_n:
            return
        if reg.codigo_sun_factory:
            self.por_sf.setdefault((inv_n, _cgm_norm(reg.codigo_sun_factory)), reg)
        if reg.nombre_proyecto_ref:
            self.por_ref.setdefault((inv_n, _cgm_norm(reg.nombre_proyecto_ref)), reg)
        if reg.proyecto_id is not None:
            self.por_pid.setdefault((inv_n, reg.proyecto_id), reg)

    def buscar(self, inv, nombre, sf, pid):
        """Devuelve el registro que ya representa este contrato, o None."""
        inv_n = _cgm_norm(inv)
        if not inv_n:
            return None
        if sf:
            hit = self.por_sf.get((inv_n, _cgm_norm(sf)))
            if hit is not None:
                return hit
        hit = self.por_ref.get((inv_n, _cgm_norm(nombre)))
        if hit is not None:
            return hit
        if pid is not None:
            return self.por_pid.get((inv_n, pid))
        return None


def _run_representacion_inversionista_sync() -> None:
    """Vincula cada contrato de representacion con el inversionista de su planta
    y cierra los que quedaron colgando.

    Existe porque `contratos_servicio.inversionista_nombre` es texto libre y la
    participacion real vive en `proyecto_inversionistas`. Sin este puente, la
    tabla de Representacion mostraba "Vigente" contratos cuyo inversionista ya
    habia salido: MGS 0024 San Diego Sur salia con tres, cuando solo uno de los
    tres inversionistas seguia participando.

    Corre en cada arranque y es idempotente. Lo que NO hace:
      - no inventa vinculos: si el nombre no identifica a un unico inversionista
        de la planta, el contrato queda sin vincular y se resuelve a mano;
      - no pisa una `fecha_fin` puesta a mano, solo rellena la que este vacia;
      - no reabre nada: solo pasa de 'vigente' a 'terminado'.

    La decision de cerrar automaticamente la tomo el equipo (2026-08-26). Un
    contrato reabierto a mano se volvera a cerrar en el siguiente arranque
    mientras la participacion siga terminada, porque el estado se deriva del
    dato duro y no al contrario.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from sqlalchemy.orm import sessionmaker
    from app.models.contratos import ContratoServicio
    from app.models.proyectos import ProyectoInversionista
    from app.services.representacion_inversionista import cierre_de, emparejar

    # Colombia es UTC-5 sin horario de verano y el contenedor corre en UTC. Con
    # `date.today()`, entre las 19:00 y medianoche de Bogota el servidor ya esta
    # en el dia siguiente y cerraria un contrato un dia antes de tiempo.
    hoy = _dt.now(_tz(_td(hours=-5))).date()

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        contratos = db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "representacion",
            ContratoServicio.proyecto_id.isnot(None),
        ).all()
        if not contratos:
            return

        proyecto_ids = {c.proyecto_id for c in contratos}
        participaciones: dict[int, list] = {}
        for p in db.query(ProyectoInversionista).filter(
                ProyectoInversionista.proyecto_id.in_(proyecto_ids)).all():
            participaciones.setdefault(p.proyecto_id, []).append(p)

        vinculados, sin_vincular = 0, 0
        for c in contratos:
            if c.inversionista_id is not None:
                continue
            pareja = emparejar(c, participaciones.get(c.proyecto_id, []))
            if pareja:
                c.inversionista_id = pareja.cliente_id
                vinculados += 1
            elif c.inversionista_nombre:
                sin_vincular += 1

        cerrados = 0
        for c in contratos:
            cierre = cierre_de(c, participaciones.get(c.proyecto_id, []), hoy)
            if not cierre:
                continue
            c.estado = "terminado"
            if cierre.poner_fecha:
                c.fecha_fin = cierre.fecha_fin
            cerrados += 1

        db.commit()
        if vinculados or cerrados or sin_vincular:
            print(f"[repr inversionista] {vinculados} vinculados, {cerrados} cerrados, "
                  f"{sin_vincular} sin vincular (se resuelven a mano)")
    except Exception as e:
        db.rollback()
        print(f"[repr inversionista] ERROR: {e}")
    finally:
        db.close()


def _run_cgm_seed() -> None:
    """
    Carga y mantiene contratos CGM/Representacion.
    Idempotente: dedupea por (inversionista + planta) con nombres normalizados.
    Corre en cada startup: inserta nuevos y repara proyecto_id NULL.
    """
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
        por_nombre = {_cgm_norm(r[1]): r[0] for r in proyectos_rows if r[1]}
        por_tsf    = {_cgm_norm(r[2]): r[0] for r in proyectos_rows if r[2]}

        def _buscar(nombre, sf):
            return _cgm_buscar_proyecto(nombre, sf, por_nombre, por_tsf)

        # ── Paso 1: insertar contratos faltantes ─────────────────────────────────
        # El dedup se hace en memoria y no con un filtro SQL: hay que comparar
        # nombres normalizados, y hay que poder reconocer un contrato por su
        # proyecto_id cuando le falta el nombre de referencia. Son ~112 filas.
        existentes = db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "representacion"
        ).all()

        indice = _CgmIndice()
        for reg in existentes:
            indice.indexar(reg)

        insertados = 0
        docs_pendientes = []  # (nuevo, enlace) -- se crean tras el commit, cuando nuevo.id ya existe
        for c in _CGM_CONTRATOS:
            nombre  = c.get("proyecto_nombre", "")
            inv     = c.get("inversionista_nombre")
            sf      = c.get("codigo_sun_factory")
            pid     = _buscar(nombre, sf)

            ya = indice.buscar(inv, nombre, sf, pid)
            if ya is not None:
                # Retroalimentar los campos que el registro no traia, para que la
                # proxima corrida lo encuentre por cualquiera de los tres indices.
                if not ya.nombre_proyecto_ref:
                    ya.nombre_proyecto_ref = nombre
                if sf and not ya.codigo_sun_factory:
                    ya.codigo_sun_factory = sf
                indice.indexar(ya)
                continue

            fecha_str = c.get("fecha_firma_contrato")
            fecha = date.fromisoformat(fecha_str) if fecha_str else None

            nuevo = ContratoServicio(
                proyecto_id=pid,
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
            )
            db.add(nuevo)
            enlace = c.get("enlace_drive")
            if enlace:
                docs_pendientes.append((nuevo, enlace))
            # Indexar el recien creado: si el propio seed repite la misma dupla
            # (inversionista + planta), la segunda vuelta lo encuentra en vez de
            # insertar otra copia.
            indice.indexar(nuevo)
            insertados += 1

        db.commit()
        if insertados:
            print(f"[cgm seed] {insertados} contratos nuevos insertados")

        if docs_pendientes:
            from app.services.documentos import set_enlace_documento
            for nuevo, enlace in docs_pendientes:
                set_enlace_documento(db, contrato_servicio_id=nuevo.id, url=enlace,
                                      nombre="Enlace Drive del contrato")
            db.commit()

        # ── Paso 2: reparar proyecto_id = NULL en registros existentes ────────────
        # Repara menos que antes, a proposito: _cgm_buscar_proyecto ya no adivina
        # por palabras. Lo que no se resuelve por codigo Sun Factory o por numero
        # de planta se queda en NULL y sale como "Sin proyecto" en
        # Servicios > Representacion, donde se asigna a mano. Este paso nunca
        # toca un proyecto_id ya asignado.
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
        # Sin `if`: el silencio era ambiguo -- podia significar "repare 0" o
        # "revente antes de llegar aca". Y el pendiente sale en el mismo log,
        # para no tener que ir a consultarlo: si `reparados` es 0 y `sin_pid`
        # no baja nunca, son contratos cuyo nombre no cruza y el seed reintenta
        # el mismo matching fallido en cada arranque.
        sin_pid_restantes = db.execute(text(
            "SELECT count(*) FROM contratos_servicio WHERE proyecto_id IS NULL"
        )).scalar()
        print(f"[cgm seed] {reparados} proyecto_id reparados; "
              f"{sin_pid_restantes} contratos siguen sin proyecto_id")

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

            results = data.get("results") if isinstance(data, dict) else None
            points = results.get("points") if isinstance(results, dict) else None
            unit = (results.get("unit") or "kWh").strip().lower() if isinstance(results, dict) else "kwh"
            factor = 1000.0 if unit == "mwh" else 1.0

            day_rows = []
            if isinstance(points, list):
                for item in points:
                    if not isinstance(item, dict):
                        continue
                    d = item.get("time") or item.get("date") or item.get("day")
                    val = item.get("kwh")
                    if val is None:
                        val = item.get("value") or item.get("energy")
                    if d and val is not None:
                        kwh = float(val) * factor
                        if kwh > 0:
                            day_rows.append((str(d)[:10], round(kwh, 3)))

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


def _scheduled_gen_promedio_recalcular():
    """Recalcula gen_mensual_promedio_mwh (ventana móvil de 30 días) para
    todos los proyectos en operación. Antes solo se recalculaba por llamada
    manual al endpoint (POST /proyectos/gen-promedio/recalcular) -- sin
    scheduler ni botón en el frontend que lo disparara, quedaba desactualizado
    en silencio (17 días sin tocar, confirmado 2026-08-27) mientras
    comercial.py/vista_contratos.py lo siguen tratando como dato confiable
    para las vistas de contrato. Respeta los valores cargados a mano
    (force=False, ver gen_promedio.decidir) -- mismo criterio que
    comercializacion_backfill, con quien comparte franja horaria."""
    import asyncio
    try:
        db = SessionLocal()
        try:
            from app.services import gen_promedio
            res = asyncio.run(gen_promedio.recalcular(db, dry_run=False, force=False))
            if "error" in res:
                print(f"[gen_promedio_recalcular] Failed: {res['error']}")
            else:
                print(f"[gen_promedio_recalcular] OK — {res['n_actualizados']} actualizados, "
                      f"{res['n_sin_datos']} sin datos, {res['n_saltados']} saltados, "
                      f"{res['n_fallidos']} fallidos")
        except Exception as e:
            print(f"[gen_promedio_recalcular] Failed: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[gen_promedio_recalcular] Failed to get DB session: {e}")


def _scheduled_comercializacion_backfill():
    """Rellena la fecha de inicio de comercialización (primer día con generación
    real) para proyectos que aún no la tienen. Corre diariamente; idempotente y
    respeta las fechas editadas a mano. Así una planta nueva entra a Cumplimiento
    en cuanto registra su primera generación."""
    try:
        db = SessionLocal()
        try:
            from app.services.comercializacion import backfill_comercializacion
            res = backfill_comercializacion(db, force=False, dry_run=False)
            print(f"[comercializacion_backfill] OK — {len(res.get('actualizados', []))} fechas nuevas, "
                  f"{len(res.get('sin_generacion', []))} sin generación, "
                  f"{len(res.get('sin_identificador', []))} sin identificador")
        except Exception as e:
            print(f"[comercializacion_backfill] Failed: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[comercializacion_backfill] Failed to get DB session: {e}")


def _scheduled_comercial_backfill():
    """Crea la Oportunidad que le falta a un cliente con relacion comercial
    real (ContratoServicio o PPA) y sin Oportunidad -- el hueco que dejan los
    clientes creados por el flujo directo (POST /clientes + contrato a mano)
    en vez del pipeline de Comercial. Corre diariamente; idempotente. No migra
    inversionistas puros (sin contrato/PPA): ver docstring de
    _ejecutar_backfill en app/api/v1/comercial.py."""
    try:
        db = SessionLocal()
        try:
            from app.api.v1.comercial import _ejecutar_backfill
            res = _ejecutar_backfill(db, usuario_id=None, dry_run=False,
                                     solo_con_relacion_comercial=True)
            print(f"[comercial_backfill] OK — {res['clientes_a_migrar']} clientes migrados, "
                  f"{res['proyectos_a_vincular']} proyectos vinculados")
        except Exception as e:
            print(f"[comercial_backfill] Failed: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[comercial_backfill] Failed to get DB session: {e}")


def _scheduled_reporte_energia():
    """Corre el clasificador de Reporte de Energía (Generación + Consumo)
    para el día anterior, hora Bogotá -- a esa hora el reporte CGM de Quoia
    ya suele estar asentado (ver hallazgos de sesión: Cedillanos/Baraya/La
    Puya, el reporte de un día suele llegar completo entre las 9 y las 10am
    del día siguiente). ejecutar_dia_background ya maneja su propia sesión
    de BD, logging y registro en _ULTIMAS_CORRIDAS (mismo mecanismo que usa
    POST /ejecutar) -- no hace falta duplicar nada acá, solo calcular la
    fecha y llamarla."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.services.reporte_energia.orquestador import ejecutar_dia_background

    fecha = (datetime.now(ZoneInfo(settings.TIMEZONE)) - timedelta(days=1)).date()
    ejecutar_dia_background(fecha)


def _scheduled_drift_medidores_reporte_energia():
    """verificar_drift_medidores_background() (pedido de Sara 2026-08-26):
    vuelve a consultar Quoia por cada fila del día anterior que sigue SIN
    revisar_manualmente y la marca si algún medidor ya cambió desde que se
    clasificó -- para que quien entre a reportar lo vea reflejado en la
    lista, sin tener que abrir cada frontera.

    Corre cada 5 min de 4:00am a 5:30am (ver registro del cron más abajo,
    mismo patrón de dos triggers que excel_terceros_cedillanos) -- después
    de las 3:30am de la clasificación, con margen para que termine (23-50
    min históricamente) y para darle varias oportunidades de detectar un
    valor que Quoia siga asentando esa madrugada, antes de que alguien
    empiece a reportar. Costo acotado: las filas que ya quedan marcadas
    revisar_manualmente=True se excluyen de la consulta en las corridas
    siguientes (ver _revisar_tabla en drift_medidores.py), así que el
    trabajo por corrida solo crece con lo que sigue sin explicar, no con
    el total de fronteras."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.services.reporte_energia.drift_medidores import verificar_drift_medidores_background

    fecha = (datetime.now(ZoneInfo(settings.TIMEZONE)) - timedelta(days=1)).date()
    resultado = verificar_drift_medidores_background(fecha)
    print(f"[reporte_energia] verificar_drift_medidores fecha={fecha} marcadas={resultado}")


def _scheduled_excel_terceros_cedillanos():
    """Revisa operaciones@unergy.io por correo nuevo de Cedillanos con su
    Excel de CGM (ver excel_terceros_email.py) -- reemplaza la carga
    manual. El reporte debe estar listo antes de las 6am, pero el correo
    de Cedillanos históricamente llega entre 3:25am y 6:10am (con
    tendencia a correrse más tarde, ver sesión 2026-08-14) -- por eso esta
    función corre cada 15 min de 4am a 6am (ver registro del cron más
    abajo) en vez de una sola vez, para minimizar el tiempo entre que el
    correo llega y el dato queda cargado. Costo despreciable: sin correo
    nuevo, cada corrida es solo un IMAP SEARCH que no toca la base de
    datos (ver revisar_correo_cedillanos)."""
    from app.services.reporte_energia.excel_terceros_email import revisar_correo_cedillanos

    revisar_correo_cedillanos()


def _scheduled_correos_mandatos():
    """Lee el buzón de mandatos y alimenta finanzas_mandatos.

    Cada hora de 7am a 7pm: los correos de la revisoría y los envíos a
    inversionistas llegan en horario laboral. Sin correos nuevos la corrida es
    solo un IMAP SEARCH que no toca la base.

    Tres pasadas -- lo que llega de la revisoría, lo que Jessica manda a los
    inversionistas, y lo que sale hacia la revisoría (carpeta Enviados, la que
    permite saber cuántos mandatos se enviaron). Transacción por correo, y la
    deduplicación va por Message-ID, así que una corrida interrumpida retoma
    donde quedó.

    El buzón es de una persona y nunca se modifica: todo `select` va con
    readonly=True y no se marca nada como leído.

    Reemplaza al diagnóstico que corrió mientras se verificaba la conexión
    (app/services/mandatos/diagnostico.py, que ya se puede borrar). El endpoint
    GET /mandatos/diagnostico-imap sigue disponible para probar a demanda.
    """
    from app.services.mandatos.finanzas_sync import revisar_correos_finanzas

    revisar_correos_finanzas()


def _scheduled_cerrar_contratos_vencidos():
    """Mueve a 'terminado' las ofertas cuyo contrato PPA ya pasó su fecha_fin.

    Diario e idempotente. Sin esto la etapa mentiría: nadie va a entrar al CRM
    el día que vence un contrato a moverlo a mano."""
    try:
        db = SessionLocal()
        try:
            from app.services.comercial import cerrar_contratos_vencidos
            cerradas = cerrar_contratos_vencidos(db)
            print(f"[comercial_cierres] OK — {len(cerradas)} oferta(s) a terminado"
                  + (f": {[c['codigo'] for c in cerradas]}" if cerradas else ""))
        except Exception as e:
            print(f"[comercial_cierres] Failed: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[comercial_cierres] Failed to get DB session: {e}")


def _scheduled_tsf_sync():
    """Sincronización periódica del pipeline TSF → tabla proyectos (cada 6 h)."""
    try:
        db = SessionLocal()
        try:
            from app.services.tsf_sync import sync_tsf_projects
            stats = sync_tsf_projects(db)
            print(f"[tsf_sync] OK — creados={stats.get('creados', 0)} "
                  f"actualizados={stats.get('actualizados', 0)} errores={stats.get('errores', 0)}")
        except Exception as e:
            print(f"[tsf_sync] Failed: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"[tsf_sync] Failed to get DB session: {e}")


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


def _alerta_emails() -> list[str]:
    """Destinatarios de las alertas de vencimiento (PPA y Representacion/CGM
    comparten el mismo grupo -- ver settings.PPA_ALERT_EMAILS)."""
    from app.jobs.ppa_expiration_checker import _parse_alert_emails
    return _parse_alert_emails(settings.PPA_ALERT_EMAILS)


def _scheduled_representacion_alertas():
    """
    Revisa aniversarios de contratos CGM/Representación.
    Envía email 30 y 15 días antes del aniversario a _alerta_emails().
    Corre diariamente a las 08:00.
    """
    from datetime import date, timedelta

    try:
        from app.services.email_service import _smtp_send, _log_envio
        from app.core.config import settings as _s
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        if not _s.SMTP_HOST:
            return

        # Antes esto leía data/DataCGM.json. Ahora la fuente es la tabla, que es
        # lo que la plataforma muestra y deja editar: un cambio de tarifa o de
        # fecha de firma hecho en la UI se refleja en la alerta.
        from sqlalchemy.orm import sessionmaker
        from app.models.contratos import ContratoServicio

        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            filas = db.query(ContratoServicio).filter(
                ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.fecha_firma_contrato.isnot(None),
            ).all()
            contratos = [{
                "Firma contrato": r.fecha_firma_contrato.isoformat(),
                "Proyecto": r.nombre_proyecto_ref or (
                    r.proyecto.nombre_comercial if r.proyecto else ""),
                "Inversionista": r.inversionista_nombre or "",
                "Tarifa CGM (kWh)": float(r.tarifa_cgm) if r.tarifa_cgm is not None else 0,
                "Tarifa Representación (kWh)": (
                    float(r.tarifa_representacion) if r.tarifa_representacion is not None else 0),
            } for r in filas]
        finally:
            db.close()

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

                destinatarios = _alerta_emails()
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = _s.SMTP_FROM
                msg["To"] = ", ".join(destinatarios)
                msg.attach(MIMEText(body_html, "html", "utf-8"))

                try:
                    _smtp_send(msg, destinatarios)
                    _log_envio(
                        destinatarios=[{"email": e, "tipo": "to"} for e in destinatarios],
                        subject=subject,
                        tipo="alerta_cgm",
                        success=True,
                    )
                    alertas_enviadas += 1
                except Exception as exc:
                    _log_envio(
                        destinatarios=[{"email": e, "tipo": "to"} for e in destinatarios],
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


def _scheduled_ppa_expiration_checker():
    """Alertas proactivas de vencimiento de contratos PPA -- ver
    app/jobs/ppa_expiration_checker.py para la logica completa (umbrales
    90/60/30 dias, idempotencia via constraint unico, correo best-effort)."""
    try:
        from app.jobs.ppa_expiration_checker import check_ppa_expirations
        creadas = check_ppa_expirations()
        if creadas:
            print(f"[ppa_expiration_checker] {len(creadas)} alertas nuevas")
    except Exception as e:
        print(f"[ppa_expiration_checker] ERROR: {e}")


_OM_IPC_SEED = [
    {"año": 2024, "tasa": 0.0928, "confirmado": True, "fuente": "DANE"},
    {"año": 2025, "tasa": 0.0520, "confirmado": True, "fuente": "DANE"},
    {"año": 2026, "tasa": 0.0510, "confirmado": True, "fuente": "DANE"},
]

# Política del seed (no destructiva sobre datos del equipo):
#   - fecha_firma_contrato, tarifa_base y fecha_inicio_om: SOLO se rellenan si
#     están NULL; nunca se sobreescribe un valor ya cargado. Sirve de respaldo
#     inicial (p.ej. BD nueva); la fuente de verdad son los campos de la UI
#     (Proyecto>Detalle>Servicios>Operación>Mantenimiento).
_OM_PROYECTOS_SEED = [
    {"nombre": "Minigranja Solar Uruaco",            "fecha_firma": "2022-09-10", "fecha_inicio_om": "2023-11-15", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Baraya",             "fecha_firma": None,         "fecha_inicio_om": None,         "valor_base_anual": None},
    {"nombre": "Minigranja Solar Cañahuate",          "fecha_firma": "2023-09-19", "fecha_inicio_om": None,         "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Gandalf",            "fecha_firma": "2023-09-19", "fecha_inicio_om": None,         "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Paz Vallenata",   "fecha_firma": "2024-08-23", "fecha_inicio_om": "2024-08-13", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Perijá",             "fecha_firma": "2024-08-23", "fecha_inicio_om": None,         "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Molino",          "fecha_firma": "2024-08-23", "fecha_inicio_om": "2024-02-20", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Paz Verso",       "fecha_firma": "2024-08-23", "fecha_inicio_om": "2024-09-30", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Esmeralda",          "fecha_firma": "2024-08-23", "fecha_inicio_om": "2025-02-26", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Son",             "fecha_firma": "2025-01-19", "fecha_inicio_om": "2025-02-16", "valor_base_anual": None},
    {"nombre": "Minigranja Solar La Puya",            "fecha_firma": "2024-08-23", "fecha_inicio_om": "2025-02-19", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Villanueva",         "fecha_firma": "2024-08-23", "fecha_inicio_om": "2025-07-25", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Merengue",           "fecha_firma": "2026-03-18", "fecha_inicio_om": "2025-04-16", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar La Reserva",         "fecha_firma": "2025-05-10", "fecha_inicio_om": "2025-04-25", "valor_base_anual": 36880000},
    {"nombre": "Nestlé",                              "fecha_firma": "2025-12-09", "fecha_inicio_om": None,         "valor_base_anual": 78000000},
    {"nombre": "Minigranja Solar Ibirico",            "fecha_firma": "2024-12-20", "fecha_inicio_om": "2025-07-21", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar El Olimpo",          "fecha_firma": "2024-08-23", "fecha_inicio_om": "2025-07-20", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar La Mesa",            "fecha_firma": "2024-08-23", "fecha_inicio_om": "2025-09-12", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar San Diego Sur",      "fecha_firma": "2025-10-20", "fecha_inicio_om": "2025-10-30", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Valencia Oriente 1", "fecha_firma": "2026-03-18", "fecha_inicio_om": "2026-01-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar La Cacica",          "fecha_firma": "2026-01-19", "fecha_inicio_om": "2026-01-28", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Las Piloneras",      "fecha_firma": "2026-01-19", "fecha_inicio_om": "2026-02-04", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Valencia Oriente 2", "fecha_firma": "2026-03-18", "fecha_inicio_om": "2026-01-18", "valor_base_anual": 54000000},
    {"nombre": "Minigranja Solar Cumbia",             "fecha_firma": "2025-01-01", "fecha_inicio_om": "2026-02-06", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Copey",              "fecha_firma": "2025-01-01", "fecha_inicio_om": "2026-03-05", "valor_base_anual": 48000000},
    {"nombre": "Minigranja Solar Chiriguana 2",       "fecha_firma": None,         "fecha_inicio_om": None,         "valor_base_anual": None},
    {"nombre": "Minigranja Solar Chiriguana 4",       "fecha_firma": None,         "fecha_inicio_om": None,         "valor_base_anual": None},
]


def _run_om_seed() -> None:
    """
    Siembra datos O&M: tasas IPC y fechas/base de los contratos de mantenimiento.

    NO crea contratos ni huérfanos: actualiza los contratos de mantenimiento que
    YA existen, emparejándolos por nombre. Política no destructiva sobre datos del
    equipo: fecha_firma_contrato, tarifa_base y fecha_inicio_om solo se rellenan
    si están NULL. Además hace un backfill idempotente fecha_inicio → fecha_inicio_om
    (unificación de la "Fecha de inicio O&M" en una sola columna).
    """
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.models.om import IPCTasa
    from app.models.contratos import ContratoServicio
    from app.services.om_calculator import om_keys, om_match_seed

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # ── IPC seed ──────────────────────────────────────────────────────────
        for item in _OM_IPC_SEED:
            existing = db.query(IPCTasa).filter(IPCTasa.año == item["año"]).first()
            if not existing:
                db.add(IPCTasa(**item))
        db.commit()

        # ── Actualizar contratos mantenimiento existentes ─────────────────────
        def _fecha(s):
            return date.fromisoformat(s) if s else None

        seed_keys = [(it, om_keys(it["nombre"])) for it in _OM_PROYECTOS_SEED]
        contratos = db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "mantenimiento"
        ).all()

        actualizados = 0
        usados = set()
        for c in contratos:
            nombre_disp = (c.proyecto.nombre_comercial if c.proyecto else c.prestador_nombre) or ""
            it = om_match_seed(nombre_disp, seed_keys)
            if it is None:
                continue
            usados.add(it["nombre"])
            firma = _fecha(it["fecha_firma"])
            inicio_om = _fecha(it["fecha_inicio_om"])
            base = it["valor_base_anual"]

            cambio = False
            if firma is not None and c.fecha_firma_contrato is None:
                c.fecha_firma_contrato = firma
                cambio = True
            if base is not None and c.tarifa_base is None:
                c.tarifa_base = base
                cambio = True
            if inicio_om is not None and c.fecha_inicio_om is None:
                c.fecha_inicio_om = inicio_om
                cambio = True
            if cambio:
                actualizados += 1

        # ── Unificación de columnas O&M (idempotente, no destructiva) ─────────
        # La "Fecha de inicio O&M" pasa a vivir SOLO en fecha_inicio_om. Antes el
        # diálogo la guardaba en fecha_inicio; copiamos ese valor donde aún no haya
        # fecha_inicio_om. Solo rellena NULLs → nunca cambia una fecha ya existente
        # (por tanto no altera ninguna indexación).
        backfill = 0
        for c in contratos:
            if c.fecha_inicio_om is None and c.fecha_inicio is not None:
                c.fecha_inicio_om = c.fecha_inicio
                backfill += 1

        db.commit()
        faltantes = [it["nombre"] for it, _ in seed_keys if it["nombre"] not in usados]
        print(f"[om_seed] {actualizados} contratos actualizados; backfill inicio_om={backfill}; sin match: {faltantes}")

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


_ARR_IPC_SEED = [
    {"año": 2023, "tasa": 0.0928, "confirmado": True, "fuente": "DANE"},
    {"año": 2024, "tasa": 0.0520, "confirmado": True, "fuente": "DANE"},
    {"año": 2025, "tasa": 0.0510, "confirmado": True, "fuente": "DANE"},
]

_ARR_PROYECTOS_SEED = [
    {"codigo": "COLATLT14P2_LURUACO_SUR",            "nombre": "Minigranja Solar Uruaco",            "fecha_firma": "2023-11-15", "valor_base": 666666.67,  "canon": 840024},
    {"codigo": None,                                 "nombre": "Minigranja Solar Cañahuate",          "fecha_firma": None,         "valor_base": None,       "canon": None},
    {"codigo": None,                                 "nombre": "Minigranja Solar Gandalf",            "fecha_firma": None,         "valor_base": None,       "canon": None},
    {"codigo": None,                                 "nombre": "Minigranja Solar Perijá",             "fecha_firma": None,         "valor_base": None,       "canon": None},
    {"codigo": "COLCEST9P1_LA-PAZ_OCCIDENTE",        "nombre": "Minigranja Solar La Paz Vallenata",   "fecha_firma": "2023-09-01", "valor_base": 4300000.02, "canon": 4691746.88},
    {"codigo": "COLLAGT19P2_EL-MOLINO_NORTE",        "nombre": "Minigranja Solar El Molino",          "fecha_firma": "2024-02-20", "valor_base": 750000,     "canon": 829239},
    {"codigo": "COLCEST2P3_LA-PAZ_OCCIDENTE",        "nombre": "Minigranja Solar La Paz Verso",       "fecha_firma": "2024-03-11", "valor_base": 1100000,    "canon": 1326782.4},
    {"codigo": "COLCEST45P5_VALLEDUPAR_SUR",         "nombre": "Minigranja Solar La Puya",            "fecha_firma": "2025-03-04", "valor_base": 1566199.7,  "canon": 1646075},
    {"codigo": "COLCEST17P1_LA-PAZ_NORTE",           "nombre": "Minigranja Solar Esmeralda",          "fecha_firma": "2024-08-05", "valor_base": 1000000,    "canon": 1105652},
    {"codigo": "COLLAGT27P2_VILLANUEVA_NORTE",       "nombre": "Minigranja Solar Villanueva",         "fecha_firma": "2024-02-16", "valor_base": 1000000,    "canon": 1094720},
    {"codigo": "COLSANT4P2_LOS-SANTOS_OCCIDENTE",    "nombre": "Minigranja Solar El Olimpo",          "fecha_firma": "2024-05-14", "valor_base": 875000,     "canon": 967446},
    {"codigo": "COLSANT10P1_LOS-SANTOS_NORTE",       "nombre": "Minigranja Solar La Mesa",            "fecha_firma": "2025-02-07", "valor_base": 1440000,    "canon": 1592139},
    {"codigo": "COLCEST53P1_LA-PAZ_OCCIDENTE",       "nombre": "Minigranja Solar La Paz Leyenda",     "fecha_firma": None,         "valor_base": None,       "canon": None},
    {"codigo": "COLSUCT17P2_GALERAS_SUR",            "nombre": "Minigranja Solar Baraya",             "fecha_firma": None,         "valor_base": None,       "canon": None},
    {"codigo": "COLCEST45P1_VALLEDUPAR_SUR",         "nombre": "Minigranja Solar El Son",             "fecha_firma": "2025-03-20", "valor_base": 1566199.7,  "canon": 1645763},
    {"codigo": "COLCEST49P2_LA-JAGUA-DE-IBIRICO_NORTE", "nombre": "Minigranja Solar Ibirico",         "fecha_firma": None,         "valor_base": 1024604.167, "canon": 1024604.167},
    {"codigo": "COLCEST45P7_VALLEDUPAR_SUR",         "nombre": "Minigranja Solar Merengue",           "fecha_firma": "2025-03-04", "valor_base": 1566199.7,  "canon": 1646075.85},
    {"codigo": "COLSANT9P1_SABANA-DE-TORRES_OCCIDENTE", "nombre": "Minigranja Solar La Reserva",      "fecha_firma": "2024-12-19", "valor_base": 2437499.99, "canon": 1347513.38},
    {"codigo": "COLCEST38P1_SAN-DIEGO_SUR",          "nombre": "Minigranja Solar San Diego Sur",      "fecha_firma": "2024-04-16", "valor_base": 833333.34,  "canon": 833333.25},
    {"codigo": "COLCEST74P1_VALLEDUPAR_SUR",         "nombre": "Minigranja Solar Valencia Oriente 1", "fecha_firma": "2025-03-06", "valor_base": 1621500,    "canon": 1704196.5},
    {"codigo": "COLCEST74P2_VALLEDUPAR_SUR",         "nombre": "Minigranja Solar Valencia Oriente 2", "fecha_firma": "2025-06-03", "valor_base": 1621500,    "canon": 1704196.5},
    {"codigo": "COLCEST55P1_VALLEDUPAR_NORTE",       "nombre": "Minigranja Solar La Cacica",          "fecha_firma": "2025-02-27", "valor_base": 1145833,    "canon": 1204270.83},
    {"codigo": "COLCEST55P2_VALLEDUPAR_NORTE",       "nombre": "Minigranja Solar Las Piloneras",      "fecha_firma": "2025-02-27", "valor_base": 1145833,    "canon": 1204270.83},
    {"codigo": "COLCEST45P4",                        "nombre": "Minigranja Solar Cumbia",             "fecha_firma": "2025-03-04", "valor_base": 1488500,    "canon": 1646075.85},
    {"codigo": "COLCEST39P1",                        "nombre": "Minigranja Solar Copey",              "fecha_firma": "2024-05-24", "valor_base": 1000000,    "canon": 1105651},
    {"codigo": "COLCEST60P4",                        "nombre": "Minigranja Solar Chiriguana 2",       "fecha_firma": "2025-06-17", "valor_base": 1181000,    "canon": 1241231},
    {"codigo": "COLCEST60P2",                        "nombre": "Minigranja Solar Chiriguana 4",       "fecha_firma": "2025-06-17", "valor_base": 1311000,    "canon": 1377861},
]


def _run_arr_seed() -> None:
    """Siembra IPC y proyectos de Arriendos. Idempotente y no destructivo (fill-if-null)."""
    from datetime import date
    from sqlalchemy.orm import sessionmaker
    from app.models.arriendos import ArrIPCTasa, ArrProyecto

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        for item in _ARR_IPC_SEED:
            if not db.query(ArrIPCTasa).filter(ArrIPCTasa.año == item["año"]).first():
                db.add(ArrIPCTasa(**item))
        db.commit()

        def _fecha(s):
            return date.fromisoformat(s) if s else None

        insertados = actualizados = 0
        for it in _ARR_PROYECTOS_SEED:
            ya = None
            if it["codigo"]:
                ya = db.query(ArrProyecto).filter(ArrProyecto.codigo == it["codigo"]).first()
            if not ya:
                ya = db.query(ArrProyecto).filter(ArrProyecto.nombre == it["nombre"]).first()

            firma = _fecha(it["fecha_firma"])
            if ya:
                cambio = False
                if ya.codigo is None and it["codigo"]:
                    ya.codigo = it["codigo"]; cambio = True
                if ya.fecha_firma_contrato is None and firma is not None:
                    ya.fecha_firma_contrato = firma; cambio = True
                if ya.valor_base is None and it["valor_base"] is not None:
                    ya.valor_base = it["valor_base"]; cambio = True
                if cambio:
                    actualizados += 1
                continue

            db.add(ArrProyecto(
                codigo=it["codigo"], nombre=it["nombre"],
                fecha_firma_contrato=firma, valor_base=it["valor_base"],
                activo=True,
            ))
            insertados += 1
        db.commit()
        if insertados or actualizados:
            print(f"[arr_seed] {insertados} proyectos insertados, {actualizados} actualizados")
    except Exception as e:
        db.rollback()
        print(f"[arr_seed] ERROR: {e}")
    finally:
        db.close()


def _run_arr_limpiar_canon_archivo() -> None:
    """Limpia el residual del mecanismo canon_archivo (override manual, ya eliminado
    de la lógica de cálculo): pone en NULL cualquier valor guardado en arr_proyectos
    para que Costos>Arriendos siempre muestre el canon calculado. Idempotente
    (el WHERE hace que no repita el UPDATE una vez ya está todo en NULL)."""
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        res = db.execute(text(
            "UPDATE arr_proyectos SET canon_archivo = NULL WHERE canon_archivo IS NOT NULL"
        ))
        db.commit()
        if res.rowcount:
            print(f"[arr_limpiar_canon_archivo] {res.rowcount} filas limpiadas")
    except Exception as e:
        db.rollback()
        print(f"[arr_limpiar_canon_archivo] ERROR: {e}")
    finally:
        db.close()


def _run_fallas_tipo_backfill() -> None:
    """Corrige el tipo/título de las fallas estructuradas cuyo tipo_id había quedado
    apuntando a un tipo legacy contradictorio (p.ej. 'Fusible de string quemado' en
    fallas de red). Corre después del seed de estructura para que los tipos ya
    existan. Idempotente. Ver [[project_reporte_fallas_estructurado]]."""
    from sqlalchemy.orm import sessionmaker
    from app.api.v1.fallas import backfill_tipos_estructurados

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        rep = backfill_tipos_estructurados(db, dry_run=False)
        print(f"[startup] fallas_tipo_backfill: {rep['corregidas']} corregidas "
              f"de {rep['total_estructuradas']} fallas estructuradas")
    finally:
        db.close()


def _run_arr_backfill_contratos() -> None:
    """Crea el contrato de arriendo (ContratoServicio servicio_aplica='arriendo') en
    cada proyecto que tenga un ArrProyecto emparejado (match difuso, ignora el código
    MGS) y aún no tenga contrato de arriendo. Copia valor_base→tarifa_base y la fecha
    de suscripción. Idempotente y NO destructivo: nunca pisa un contrato existente.
    Con esto la info de arriendos vive en Proyecto>Detalle>Servicios>Operación."""
    from sqlalchemy.orm import sessionmaker
    from app.models.arriendos import ArrProyecto
    from app.models.contratos import ContratoServicio
    from app.models.proyectos import Proyecto
    from app.services.om_calculator import om_keys, om_match_seed

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        arr = db.query(ArrProyecto).filter(ArrProyecto.activo == True).all()  # noqa: E712
        arr_keys = [(a, om_keys(a.nombre)) for a in arr]
        con_arr = {c.proyecto_id for c in db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "arriendo",
            ContratoServicio.proyecto_id.isnot(None)).all()}

        creados, usados = 0, set()
        for p in db.query(Proyecto).all():
            a = om_match_seed(p.nombre_comercial or "", arr_keys)
            if a is None or a.id in usados:
                continue
            usados.add(a.id)
            if p.id in con_arr:
                continue   # ya tiene contrato de arriendo → no se toca
            db.add(ContratoServicio(
                proyecto_id=p.id,
                servicio_aplica="arriendo",
                estado="vigente",
                periodicidad_pago="mensual",
                tarifa_base=a.valor_base,
                fecha_firma_contrato=a.fecha_firma_contrato,
            ))
            creados += 1
        db.commit()
        print(f"[arr_backfill] {creados} contratos de arriendo creados desde ArrProyecto")
    except Exception as e:
        db.rollback()
        print(f"[arr_backfill] FAILED: {e}")
    finally:
        db.close()


def _backfill_arr_arrendador(db) -> int:
    """Núcleo testeable: crea 1 ArrArrendador para cada contrato de arriendo
    que aún no tenga ninguno. Idempotente (fill-if-missing)."""
    from app.models.arriendos import ArrArrendador
    from app.models.contratos import ContratoServicio
    contratos = db.query(ContratoServicio).filter(ContratoServicio.servicio_aplica == "arriendo").all()
    creados = 0
    for c in contratos:
        existe = db.query(ArrArrendador).filter(ArrArrendador.contrato_id == c.id).first()
        if existe:
            continue
        db.add(ArrArrendador(
            contrato_id=c.id,
            nombre=c.prestador_nombre or "Arrendador",
            valor_base=c.tarifa_base,
            responsable_iva=c.responsable_iva,
        ))
        creados += 1
    db.commit()
    return creados


def _run_arr_arrendador_backfill() -> None:
    """Crea el arrendador automático (nombre=prestador, valor=tarifa_base,
    responsable_iva=el del contrato) para todo ContratoServicio(arriendo) que
    aún no tenga ninguno. Idempotente."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        creados = _backfill_arr_arrendador(db)
        print(f"[arr_arrendador_backfill] {creados} arrendadores creados")
    except Exception as e:
        db.rollback()
        print(f"[arr_arrendador_backfill] FAILED: {e}")
    finally:
        db.close()


def _backfill_arr_arrendador_id(db) -> int:
    """Núcleo testeable: para cada ArrSeleccion/ArrDocumento con
    arr_arrendador_id IS NULL, resuelve vía arr_proyecto_id → ArrProyecto →
    match difuso → Proyecto → ContratoServicio(arriendo) → primer ArrArrendador
    de ese contrato, y lo asigna. Fill-if-null, nunca pisa lo ya enlazado."""
    from app.models.arriendos import ArrProyecto, ArrArrendador, ArrSeleccion, ArrDocumento
    from app.models.contratos import ContratoServicio
    from app.models.proyectos import Proyecto
    from app.services.om_calculator import om_keys, om_match_seed

    arr = db.query(ArrProyecto).filter(ArrProyecto.activo == True).all()  # noqa: E712
    arr_keys = [(a, om_keys(a.nombre)) for a in arr]
    proyectos = db.query(Proyecto).all()

    arrendador_por_arr_proyecto: dict[int, int] = {}
    for p in proyectos:
        a = om_match_seed(p.nombre_comercial or "", arr_keys)
        if a is None:
            continue
        contrato = db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "arriendo",
            ContratoServicio.proyecto_id == p.id,
        ).first()
        if contrato is None:
            continue
        arrendador = db.query(ArrArrendador).filter(
            ArrArrendador.contrato_id == contrato.id,
        ).first()
        if arrendador is None:
            continue
        arrendador_por_arr_proyecto[a.id] = arrendador.id

    actualizados = 0
    for sel in db.query(ArrSeleccion).filter(ArrSeleccion.arr_arrendador_id.is_(None)).all():
        arrendador_id = arrendador_por_arr_proyecto.get(sel.arr_proyecto_id)
        if arrendador_id is None:
            continue
        sel.arr_arrendador_id = arrendador_id
        actualizados += 1

    for doc in db.query(ArrDocumento).filter(ArrDocumento.arr_arrendador_id.is_(None)).all():
        if doc.arr_proyecto_id is None:
            continue
        arrendador_id = arrendador_por_arr_proyecto.get(doc.arr_proyecto_id)
        if arrendador_id is None:
            continue
        doc.arr_arrendador_id = arrendador_id
        actualizados += 1

    db.commit()
    return actualizados


def _run_arr_arrendador_id_backfill() -> None:
    """Enlaza ArrSeleccion/ArrDocumento existentes (sin arr_arrendador_id) al
    arrendador correspondiente del contrato de arriendo del proyecto emparejado.
    Idempotente, fill-if-null."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        actualizados = _backfill_arr_arrendador_id(db)
        print(f"[arr_arrendador_id_backfill] {actualizados} registros enlazados a arrendador")
    except Exception as e:
        db.rollback()
        print(f"[arr_arrendador_id_backfill] FAILED: {e}")
    finally:
        db.close()


def _backfill_arr_documento_proyecto_id(db) -> int:
    """Núcleo testeable: para cada ArrDocumento con proyecto_id IS NULL, resuelve
    vía arr_proyecto_id → ArrProyecto → match difuso → Proyecto, y lo asigna.
    Fill-if-null, nunca pisa lo ya enlazado."""
    from app.models.arriendos import ArrProyecto, ArrDocumento
    from app.models.proyectos import Proyecto
    from app.services.om_calculator import om_keys, om_match_seed

    arr = db.query(ArrProyecto).filter(ArrProyecto.activo == True).all()  # noqa: E712
    arr_keys = [(a, om_keys(a.nombre)) for a in arr]
    proyectos = db.query(Proyecto).all()

    proyecto_por_arr_proyecto: dict[int, int] = {}
    for p in proyectos:
        a = om_match_seed(p.nombre_comercial or "", arr_keys)
        if a is None:
            continue
        proyecto_por_arr_proyecto[a.id] = p.id

    actualizados = 0
    for doc in db.query(ArrDocumento).filter(ArrDocumento.proyecto_id.is_(None)).all():
        if doc.arr_proyecto_id is None:
            continue
        proyecto_id = proyecto_por_arr_proyecto.get(doc.arr_proyecto_id)
        if proyecto_id is None:
            continue
        doc.proyecto_id = proyecto_id
        actualizados += 1

    db.commit()
    return actualizados


def _run_arr_documento_proyecto_id_backfill() -> None:
    """Enlaza ArrDocumento existentes (sin proyecto_id) al Proyecto correspondiente
    vía el ArrProyecto emparejado. Idempotente, fill-if-null."""
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        actualizados = _backfill_arr_documento_proyecto_id(db)
        print(f"[arr_documento_proyecto_id_backfill] {actualizados} registros enlazados a proyecto")
    except Exception as e:
        db.rollback()
        print(f"[arr_documento_proyecto_id_backfill] FAILED: {e}")
    finally:
        db.close()


def _run_ppa_responsables_seed() -> None:
    """Siembra el catálogo de empresas responsables de PPA (Unergy / Externo) y hace
    la clasificación inicial de los contratos. Idempotente; la clasificación es
    ONE-SHOT (ver sembrar_responsables_ppa) para que un redeploy no revierta lo que
    se cambió a mano desde la UI. Los contratos externos que no casen por nombre
    quedan en Unergy y salen listados en el log."""
    from app.core.database import SessionLocal
    from app.api.v1.ppa import sembrar_responsables_ppa

    db = SessionLocal()
    try:
        rep = sembrar_responsables_ppa(db)
        if rep["clasifico"]:
            print(f"[startup] ppa_responsables_seed: Unergy={rep['unergy']} Externo={rep['externo']}"
                  + (f" · SIN MATCH (quedaron en Unergy): {rep['sin_match']}" if rep["sin_match"] else ""))
        else:
            print("[startup] ppa_responsables_seed: catálogo ok, clasificación ya hecha (se omite)")
    finally:
        db.close()


def _run_comercial_dedup() -> None:
    """Fusiona clientes-prospecto que el import creó por duplicado cuando ya
    existía el cliente operativo (match por planta→dueño o nombre exacto).
    Conservador + soft-delete (reversible) + idempotente. Corre tras el import."""
    from types import SimpleNamespace
    from app.core.database import SessionLocal
    from app.api.v1.comercial import dedup_clientes

    db = SessionLocal()
    try:
        admin_id = None
        try:
            from app.models.usuarios import Usuario
            adm = db.query(Usuario).filter(Usuario.rol == "admin").first()
            admin_id = adm.id if adm else None
        except Exception:
            admin_id = None
        current = SimpleNamespace(id=admin_id, rol=SimpleNamespace(value="admin"))
        res = dedup_clientes(dry_run=False, umbral=0.85, db=db, current=current)
        print(f"[startup] comercial_dedup: prospectos={res['prospectos']} "
              f"fusionados={res['fusionados']} sin_canonico={res['sin_canonico']}")
    finally:
        db.close()


def _run_comercial_actualizacion() -> None:
    """Aplica la actualización comercial de julio 2026: fechas de envío sacadas
    de los correos de Alejandro y los estados que reportó en la reunión del 28.

    Corre SIEMPRE en seco primero y deja el reporte en los logs. Es one-shot:
    la señal de "ya aplicado" es la marca que llevan todas las gestiones que
    inserta, así que un deploy posterior no vuelve a pisar el trabajo que el
    equipo comercial haga a mano. COMERCIAL_REAPLICAR_ACTUALIZACION fuerza
    volver a aplicarla.
    """
    import json

    from app.api.v1.comercial import ruta_actualizacion
    from app.core.database import SessionLocal
    from app.services.comercial_actualizacion import aplicar, validar, ya_aplicado

    ruta = ruta_actualizacion()
    if not ruta.exists():
        print("[startup] comercial_actualizacion: no hay archivo, se omite")
        return
    datos = json.loads(ruta.read_text(encoding="utf-8"))

    problemas = validar(datos)
    if problemas:
        print(f"[startup] comercial_actualizacion ABORTA — archivo invalido: {problemas[:10]}")
        return

    db = SessionLocal()
    try:
        if ya_aplicado(db) and not settings.COMERCIAL_REAPLICAR_ACTUALIZACION:
            print("[startup] comercial_actualizacion: ya aplicada, se omite")
            return
        seco = aplicar(db, datos, dry_run=True)
        print(f"[startup] comercial_actualizacion DRY-RUN: "
              f"envios={seco['envios']} estados={seco['estados']} "
              f"correcciones={seco['correcciones']} creadas={seco['creadas']} "
              f"eliminadas={seco['eliminadas']} fusiones={seco['fusiones']}")
        if seco["no_encontrados"]:
            print(f"[startup] comercial_actualizacion NO ENCONTRADOS: {seco['no_encontrados']}")
        if seco["sin_resolver"]:
            print(f"[startup] comercial_actualizacion SIN RESOLVER: {seco['sin_resolver']}")
        real = aplicar(db, datos, dry_run=False)
        print(f"[startup] comercial_actualizacion APLICADO: "
              f"envios={real['envios']} estados={real['estados']} "
              f"correcciones={real['correcciones']} creadas={real['creadas']} "
              f"eliminadas={real['eliminadas']} fusiones={real['fusiones']}")
    finally:
        db.close()


def _run_init_audit() -> None:
    """Engancha los hooks de auditoria de SQLAlchemy.

    Va DENTRO de la lista de tareas y no al final, porque los seeds escriben con
    sesiones ORM sobre tablas auditadas -- contratos_servicio, proyectos, fallas,
    clientes -- y hasta el 2026-08-26 corria despues de todas ellas: lo que
    sembraba el arranque no dejaba rastro en audit_log.

    Y no puede ir mas arriba: `audit_log` la crea _PENDING_DDLS, asi que tiene
    que correr DESPUES de column_migrations o el primer INSERT auditado falla
    porque la tabla todavia no existe.

    Las escrituras de los seeds quedan marcadas con un autor sintetico, para que
    en audit_log se distingan de una escritura anonima por API. El ContextVar es
    por contexto de ejecucion y esto corre en el hilo de _deferred_init, asi que
    no se filtra a las peticiones.

    El rotulo lo pone _deferred_init tarea por tarea (`sistema (startup: X)`), no
    esta funcion: con un solo rotulo para las 22 tareas, un pico de ruido en
    audit_log no dice cual lo produjo. El 2026-08-27 aparecieron 50.860 filas
    marcadas "sistema (seed de arranque)" en una sola tabla y en un solo dia, y
    no hubo forma de atribuirlas sin ir tarea por tarea a mano.
    """
    from app.services.audit import init_audit

    init_audit()


def _deferred_init():
    """Heavy initialization that runs in a background thread after the server is ready."""
    import time as _t
    _t0 = _t.time()
    global _mgs_scheduler

    for label, fn in [
        ("mandatos_maestra_seed", _run_mandatos_maestra_seed),
        # Justo aca: despues del DDL que crea audit_log, y ANTES de los seeds,
        # que escriben con sesiones ORM sobre tablas auditadas.
        ("init_audit", _run_init_audit),
        ("comercial_dedup", _run_comercial_dedup),
        ("comercial_actualizacion", _run_comercial_actualizacion),
        ("starlink_mapeo_seed", _run_starlink_mapeo_seed),
        ("catalog_seed", _run_catalog_seed),
        ("estructura_fallas_seed", _run_estructura_fallas_seed),
        ("tipo_migration", _run_tipo_migration),
        # Pegado a tipo_migration a proposito. Con el regex arreglado la pelea
        # por `fallas.tipo_id` ya no puede pasar; esto es la red de seguridad:
        # si alguna vez vuelve a haber dos escritores, la ventana de datos
        # inconsistentes servidos por la API dura una tarea y no trece.
        ("fallas_tipo_backfill", _run_fallas_tipo_backfill),
        ("cgm_seed", _run_cgm_seed),
        # Va DESPUES del seed CGM: vincula y cierra sobre lo que ese ya sembro.
        ("repr_inversionista_sync", _run_representacion_inversionista_sync),
        ("om_seed", _run_om_seed),
        ("arr_seed", _run_arr_seed),
        ("arr_backfill_contratos", _run_arr_backfill_contratos),
        ("arr_arrendador_backfill", _run_arr_arrendador_backfill),
        ("arr_arrendador_id_backfill", _run_arr_arrendador_id_backfill),
        ("arr_documento_proyecto_id_backfill", _run_arr_documento_proyecto_id_backfill),
        ("arr_limpiar_canon_archivo", _run_arr_limpiar_canon_archivo),
        ("ppa_responsables_seed", _run_ppa_responsables_seed),
    ]:
        try:
            # Cada tarea firma sus propias escrituras. init_audit ya corrio como
            # una tarea mas, asi que a partir de ahi el rotulo es efectivo; las
            # dos que van antes escriben DDL, no ORM.
            try:
                from app.services.audit import set_audit_user
                set_audit_user(None, f"sistema (startup: {label})")
            except Exception:
                pass
            fn()
            print(f"[startup] {label} OK ({_t.time() - _t0:.1f}s)")
        except Exception as e:
            print(f"[startup] {label} FAILED: {e}")

    # Se acabaron los seeds: lo que este hilo haga de aca en adelante no lleva
    # el rotulo de arranque.
    try:
        from app.services.audit import set_audit_user
        set_audit_user(None, None)
    except Exception:
        pass

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
                _scheduled_representacion_alertas,
                CronTrigger(hour=8, minute=0, timezone=settings.TIMEZONE),
                id="cgm_alertas",
                name="Alertas renovacion CGM/Representacion",
            )

            # 8:15 en vez de 8:00 para no competir con cgm_alertas por la misma
            # franja exacta (aunque corren en threads separados de todas formas).
            _mgs_scheduler.add_job(
                _scheduled_ppa_expiration_checker,
                CronTrigger(hour=8, minute=15, timezone=settings.TIMEZONE),
                id="ppa_expiration_checker",
                name="Alertas vencimiento PPA",
            )

            # Fecha de inicio de comercialización (primer día con generación real):
            # backfill diario para plantas que aún no la tienen. La corrida inicial
            # post-deploy se dispara a mano vía POST /cumplimiento/backfill-comercializacion.
            _mgs_scheduler.add_job(
                _scheduled_comercializacion_backfill,
                CronTrigger(hour=3, minute=30, timezone=settings.TIMEZONE),
                id="comercializacion_backfill",
                name="Backfill fecha inicio comercializacion",
            )

            # Cierra el hueco de clientes con contrato/PPA real que quedaron
            # sin Oportunidad (creados por el flujo directo, no por el
            # pipeline de Comercial). Horario propio: no compite con los de
            # arriba, que sí dependen de la API de generación de Unergy.
            _mgs_scheduler.add_job(
                _scheduled_comercial_backfill,
                CronTrigger(hour=3, minute=35, timezone=settings.TIMEZONE),
                id="comercial_backfill",
                name="Backfill Oportunidad para clientes con relacion comercial",
            )

            # 10 min antes de comercializacion_backfill -- ambos leen la misma
            # API de generación de Unergy; separarlos evita que compitan por
            # el mismo rate limit al mismo segundo exacto.
            _mgs_scheduler.add_job(
                _scheduled_gen_promedio_recalcular,
                CronTrigger(hour=3, minute=20, timezone=settings.TIMEZONE),
                id="gen_promedio_recalcular",
                name="Recalcular generación mensual promedio",
            )

            _mgs_scheduler.add_job(
                _scheduled_reporte_energia,
                # Adelantado de 4:00am a 3:30am (2026-08-21): la corrida del
                # 20-ago tardó >45 min sin terminar (vs. 23-50 min los 10
                # días previos, siempre completando las 106 filas) -- media
                # hora más de margen antes de que alguien la revise en la
                # mañana. Contrapartida asumida a propósito: lee el CGM de
                # Quoia un poco menos asentado que a las 4am (ver docstring
                # de _scheduled_reporte_energia).
                CronTrigger(hour=3, minute=30, timezone=settings.TIMEZONE),
                id="reporte_energia_clasificar",
                name="Reporte de Energía -- clasificar día anterior",
            )

            # Cada 5 min de 4:00am a 5:30am (19 corridas) -- dos triggers por
            # la misma razón que excel_terceros_cedillanos más abajo
            # (CronTrigger no soporta minutos distintos por hora en una sola
            # expresión: 4:00-4:55 cada 5 min + 5:00-5:30 cada 5 min).
            _mgs_scheduler.add_job(
                _scheduled_drift_medidores_reporte_energia,
                CronTrigger(hour=4, minute="*/5", timezone=settings.TIMEZONE),
                id="reporte_energia_drift_medidores_4am",
                name="Reporte de Energía -- drift de medidores (4:00-4:55am)",
            )
            _mgs_scheduler.add_job(
                _scheduled_drift_medidores_reporte_energia,
                CronTrigger(hour=5, minute="0,5,10,15,20,25,30", timezone=settings.TIMEZONE),
                id="reporte_energia_drift_medidores_5am",
                name="Reporte de Energía -- drift de medidores (5:00-5:30am)",
            )

            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                # Cada 15 min de 4:00am a 6:00am (9 corridas) -- el correo de
                # Cedillanos históricamente llega entre 3:25am y 6:10am (con
                # tendencia a correrse más tarde) y el reporte debe estar
                # listo antes de las 6am. Dos triggers porque CronTrigger no
                # soporta minutos distintos por hora en una sola expresión
                # (4am-5:45am cada 15 min + 6:00am exacto, el último intento
                # antes del corte).
                _mgs_scheduler.add_job(
                    _scheduled_excel_terceros_cedillanos,
                    CronTrigger(hour="4,5", minute="*/15", timezone=settings.TIMEZONE),
                    id="excel_terceros_cedillanos_am",
                    name="Reporte de Energía -- Excel de Cedillanos por correo (4-5:45am)",
                )
                _mgs_scheduler.add_job(
                    _scheduled_excel_terceros_cedillanos,
                    CronTrigger(hour=6, minute=0, timezone=settings.TIMEZONE),
                    id="excel_terceros_cedillanos_6am",
                    name="Reporte de Energía -- Excel de Cedillanos por correo (6am, último intento)",
                )

            if settings.MANDATOS_IMAP_USER and settings.MANDATOS_IMAP_PASSWORD:
                _mgs_scheduler.add_job(
                    _scheduled_correos_mandatos,
                    CronTrigger(hour="7-19", minute=5, timezone=settings.TIMEZONE),
                    id="correos_mandatos",
                    name="Mandatos -- lectura de correo por IMAP (7am-7pm)",
                )

            # Ofertas cuyo PPA ya vencio -> etapa 'terminado'. Justo despues del
            # cambio de dia para que el tablero amanezca correcto.
            _mgs_scheduler.add_job(
                _scheduled_cerrar_contratos_vencidos,
                CronTrigger(hour=0, minute=20, timezone=settings.TIMEZONE),
                id="comercial_cierres",
                name="Cerrar ofertas con contrato vencido",
            )

            _mgs_scheduler.add_job(
                _scheduled_om_ipc_check,
                CronTrigger(month=1, day=1, hour=9, minute=0, timezone=settings.TIMEZONE),
                id="om_ipc_check",
                name="Check IPC anual O&M",
            )

            _mgs_scheduler.add_job(
                _scheduled_tsf_sync,
                IntervalTrigger(hours=6),
                id="tsf_sync",
                name="Sync pipeline TSF -> proyectos",
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



@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
