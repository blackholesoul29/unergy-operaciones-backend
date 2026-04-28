"""
Pobla sub_project (topic/código base) y codigo_tsf en los proyectos existentes.

Lee data/NOMBRE TOPIC.json  → topic → nombre oficial del proyecto
Lee data/NOMBRE TFS.json    → nombre proyecto → código TSF

Matching: accent-insensitive, fuzzy (SequenceMatcher ≥ 0.72).
No sobreescribe si sub_project ya está asignado, a menos que se use --force.

Uso:
    # BD Railway (URL como argumento):
    python scripts/cargar_topics_tsf.py "postgresql+psycopg://user:pass@host:port/db"

    # O como variable de entorno:
    DATABASE_URL="postgresql+psycopg://..." python scripts/cargar_topics_tsf.py

    # BD local (.env):
    python scripts/cargar_topics_tsf.py

    # Forzar sobreescritura aunque ya tenga valor:
    python scripts/cargar_topics_tsf.py [url] --force

    # Solo mostrar qué haría (sin escribir):
    python scripts/cargar_topics_tsf.py [url] --dry-run
"""
import json
import os
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Flags ────────────────────────────────────────────────────────────────────
args = sys.argv[1:]
FORCE   = "--force"   in args
DRY_RUN = "--dry-run" in args
url_args = [a for a in args if not a.startswith("--")]

DATABASE_URL = (url_args[0] if url_args else None) or os.environ.get("DATABASE_URL")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    from sqlalchemy import create_engine
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    from app.core.database import engine

from sqlalchemy.orm import sessionmaker
from app.models.proyectos import Proyecto

Session = sessionmaker(bind=engine)

# ── Paths ────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent / "data"
TOPIC_FILE = BASE / "NOMBRE TOPIC.json"
TSF_FILE   = BASE / "NOMBRE TFS.json"

SIMILARITY_THRESHOLD = 0.72


# ── Normalización ─────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    """Lowercase, strip whitespace, remove accents."""
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


# ── Carga de archivos de datos ────────────────────────────────────────────────

def load_topic_map() -> dict[str, str]:
    """
    Retorna {topic: project_name} filtrando entradas inválidas
    (UI artifacts, nulls, entradas sin 'Project').
    Si un mismo nombre de proyecto tiene múltiples topics, conserva todos
    como lista para que el matching sepa cuál es cuál.
    """
    raw = json.loads(TOPIC_FILE.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for entry in raw:
        if not entry or not isinstance(entry, dict):
            continue
        topic = (entry.get("Topic") or "").strip()
        project = (entry.get("Project") or "").strip()
        # Filtrar artefactos de UI (sin project, o topic que es nombre de proyecto)
        if not topic or not project:
            continue
        # Topics válidos son slugs lowercase sin espacios
        if " " in topic or topic[0].isupper():
            continue
        result[topic] = project
    return result


def load_tsf_map() -> list[tuple[str, str]]:
    """
    Retorna [(nombre_proyecto, tsf), ...].
    Mantenemos lista (no dict) para poder hacer fuzzy matching contra nombres.
    """
    raw = json.loads(TSF_FILE.read_text(encoding="utf-8"))
    return [(e["Proyecto"].strip(), e["TSF"].strip()) for e in raw if e.get("Proyecto") and e.get("TSF")]


# ── Matching ──────────────────────────────────────────────────────────────────

def best_topic_for_project(nombre: str, topic_map: dict[str, str]) -> tuple[str, str, float] | None:
    """
    Busca el topic cuyo nombre oficial (Project) más se parece a `nombre`.
    Retorna (topic, project_name, score) o None si no supera el umbral.
    """
    best_topic = best_name = None
    best_score = 0.0
    for topic, project_name in topic_map.items():
        s = similarity(nombre, project_name)
        if s > best_score:
            best_score = s
            best_topic = topic
            best_name = project_name
    if best_score >= SIMILARITY_THRESHOLD:
        return best_topic, best_name, best_score
    return None


def best_tsf_for_project(nombre: str, tsf_list: list[tuple[str, str]]) -> tuple[str, str, float] | None:
    """
    Busca el TSF cuyo nombre de proyecto más se parece a `nombre`.
    Retorna (tsf_code, matched_name, score) o None.
    """
    best_tsf = best_name = None
    best_score = 0.0
    for proj_name, tsf in tsf_list:
        s = similarity(nombre, proj_name)
        if s > best_score:
            best_score = s
            best_tsf = tsf
            best_name = proj_name
    if best_score >= SIMILARITY_THRESHOLD:
        return best_tsf, best_name, best_score
    return None


# ── Script principal ──────────────────────────────────────────────────────────

def main():
    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}Cargando topics y TSF...\n")

    topic_map = load_topic_map()
    tsf_list  = load_tsf_map()
    print(f"  {len(topic_map)} topics cargados de {TOPIC_FILE.name}")
    print(f"  {len(tsf_list)} TSF cargados de {TSF_FILE.name}\n")

    db = Session()
    try:
        proyectos = db.query(Proyecto).order_by(Proyecto.nombre_comercial).all()
        print(f"  {len(proyectos)} proyectos en BD\n")

        # Rastrear topics ya asignados en esta sesión para evitar duplicados
        # (sub_project tiene restricción UNIQUE)
        topics_used: set[str] = set(
            p.sub_project for p in proyectos if p.sub_project
        )

        updated = skipped = no_match = 0
        no_match_list = []

        for p in proyectos:
            nombre = p.nombre_comercial
            changed = False

            # ── sub_project ───────────────────────────────────────────────
            if not p.sub_project or FORCE:
                match = best_topic_for_project(nombre, topic_map)
                if match:
                    topic, matched_name, score = match
                    if topic in topics_used and p.sub_project != topic:
                        print(f"  SKIP  {nombre!r} → topic '{topic}' ya asignado a otro proyecto")
                    else:
                        if not DRY_RUN:
                            p.sub_project = topic
                        topics_used.add(topic)
                        changed = True
                        print(f"  TOPIC {nombre!r}")
                        print(f"        → '{topic}'  (match: '{matched_name}', score: {score:.2f})")
                else:
                    print(f"  NO-TOPIC  {nombre!r}  (sin match ≥ {SIMILARITY_THRESHOLD})")
                    no_match_list.append(nombre)
            else:
                print(f"  OK    {nombre!r} → topic ya existe: '{p.sub_project}'")

            # ── codigo_tsf ────────────────────────────────────────────────
            if not p.codigo_tsf or FORCE:
                # Intentar con nombre comercial y también con el nombre del topic match
                best = best_tsf_for_project(nombre, tsf_list)
                if best:
                    tsf, matched_name, score = best
                    if not DRY_RUN:
                        p.codigo_tsf = tsf
                    changed = True
                    print(f"        TSF → '{tsf}'  (match: '{matched_name}', score: {score:.2f})")
            else:
                print(f"        TSF ya existe: '{p.codigo_tsf}'")

            if changed:
                updated += 1
            else:
                skipped += 1

        if not DRY_RUN:
            db.commit()
            print(f"\nOK — {updated} proyectos actualizados, {skipped} sin cambios, {len(no_match_list)} sin match de topic.")
        else:
            print(f"\n[DRY-RUN] — {updated} proyectos se actualizarían, {skipped} sin cambios, {len(no_match_list)} sin match.")

        if no_match_list:
            print(f"\nProyectos sin topic match ({len(no_match_list)}):")
            for n in no_match_list:
                print(f"  - {n}")

    except Exception as e:
        db.rollback()
        print(f"\nERROR — rollback: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
