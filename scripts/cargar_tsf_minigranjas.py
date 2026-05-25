"""
Actualiza codigo_tsf y fecha_entrada_operacion para las minigranjas listadas.

Uso:
    python scripts/cargar_tsf_minigranjas.py [DATABASE_URL] [--dry-run] [--force]
"""
import os
import sys
import unicodedata
from datetime import date
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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

# ---------------------------------------------------------------------------
# Datos de referencia: (nombre_sunfactory, codigo_tsf, fecha_fpo | None)
# ---------------------------------------------------------------------------
REFERENCIA = [
    ("MiniGranja 0001 - Uruaco",                                  "COLATLT14P2",  date(2023, 7, 18)),
    ("MiniGranja 0004 - Valle de Gandalf",                        "COLCEST61P3",  date(2024, 2, 22)),
    ("MiniGranja 0005 - Cañahuate",                               "COLCEST61P1",  date(2024, 2, 22)),
    ("MiniGranja 0006 - Perijá (La inglesa)",                     "COLCEST58P2",  date(2024, 9, 16)),
    ("MiniGranja 0007 - La Paz Vallenata (Medardo)",              "COLCEST9P1",   date(2024, 8, 13)),
    ("MiniGranja 0008 - La Paz Verso (Villa Sonia)",              "COLCEST2P3",   date(2025, 1, 18)),
    ("MiniGranja 0009 - El Molino (Macedonia)",                   "COLLAGT19P2",  date(2024, 9, 30)),
    ("MiniGranja 0010 - Villanueva (los suspiros)",               "COLLAGT27P2",  date(2025, 7, 25)),
    ("MiniGranja 0013 - La Mesa (La Virginia 1)",                 "COLSANT10P1",  date(2026, 2, 26)),
    ("MiniGranja 0014 - El Olimpo",                               "COLSANT4P2",   date(2026, 2, 26)),
    ("Minigranja 0016 - La Puya - Valledupar, Cesar (Jericó 4_Cesar)", "COLCEST45P5", date(2025, 4, 7)),
    ("MiniGranja 0017 - La Paz Esmeralda - La Esmeralda 1",      "COLCEST17P1",  date(2025, 2, 26)),
    ("Minigranja 0021 - Ibirico",                                 "COLCEST49P2",  date(2025, 7, 21)),
    ("Minigranja 0040 - La Cacica",                               "COLCEST55P1",  None),
    ("Minigranja 0041  - Las piloneras",                          "COLCEST55P2",  None),
    ("Minigranja 0075 - Chiriguaná Norte 2",                      "COLCEST60P4",  None),
    ("Minigranja 0077 - Chiriguaná Norte 4",                      "COLCEST60P2",  None),
    ("MiniGranja 0025 - El Copey Occidente",                      "COLCEST39P1",  None),
    ("Minigranja 0018 - La Paz Leyenda",                          "COLCEST53P1",  date(2024, 12, 2)),
    ("MiniGranja 0019 - El Merengue (Jericó 2_Cesar)",           "COLCEST45P7",  date(2025, 4, 16)),
    ("Minigranja 0022 - La Cumbia",                               "COLCEST45P4",  None),
    ("MiniGranja 0024 - San Diego Sur",                           "COLCEST38P1",  date(2025, 12, 7)),
    ("Minigranja 0026 - Valencia Oriente",                        "COLCEST74P1",  date(2026, 2, 13)),
    ("Minigranja 0027 - Valencia Oriente 2",                      "COLCEST74P2",  date(2026, 2, 24)),
    ("Minigranja 0015 - El Son",                                  "COLCEST45P1",  date(2025, 4, 28)),
    ("Minigranja 0002 - Baraya",                                  "COLSUCT17P2",  date(2024, 2, 18)),
    ("Minigranja 0012 - La Reserva",                              "COLSANT9P1",   date(2025, 7, 4)),
]

SIMILARITY_THRESHOLD = 0.65


def norm(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def best_match(ref_name: str, proyectos: list) -> tuple | None:
    best_p, best_score = None, 0.0
    for p in proyectos:
        s = similarity(ref_name, p.nombre_comercial)
        if s > best_score:
            best_score = s
            best_p = p
    if best_score >= SIMILARITY_THRESHOLD:
        return best_p, best_score
    return None


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Actualizando codigo_tsf y fecha_entrada_operacion...\n")

    db = Session()
    try:
        proyectos = db.query(Proyecto).order_by(Proyecto.nombre_comercial).all()
        print(f"  {len(proyectos)} proyectos en BD\n")

        updated = skipped = no_match = 0
        no_match_list = []

        for ref_name, tsf, fpo in REFERENCIA:
            result = best_match(ref_name, proyectos)
            if not result:
                print(f"  NO-MATCH  '{ref_name}'")
                no_match += 1
                no_match_list.append(ref_name)
                continue

            p, score = result
            changes = []

            if not p.codigo_tsf or FORCE:
                changes.append(f"codigo_tsf: {p.codigo_tsf!r} → {tsf!r}")
                if not DRY_RUN:
                    p.codigo_tsf = tsf
            elif p.codigo_tsf != tsf:
                print(f"  AVISO     '{p.nombre_comercial}' ya tiene TSF '{p.codigo_tsf}' (referencia: '{tsf}') — usa --force para sobreescribir")

            if fpo and (not p.fecha_entrada_operacion or FORCE):
                changes.append(f"fecha_entrada_operacion: {p.fecha_entrada_operacion} → {fpo}")
                if not DRY_RUN:
                    p.fecha_entrada_operacion = fpo
            elif fpo and p.fecha_entrada_operacion != fpo:
                print(f"  AVISO     '{p.nombre_comercial}' ya tiene FPO {p.fecha_entrada_operacion} (referencia: {fpo}) — usa --force para sobreescribir")

            if changes:
                print(f"  UPDATE    '{p.nombre_comercial}'  (match score: {score:.2f})")
                for c in changes:
                    print(f"            {c}")
                updated += 1
            else:
                print(f"  OK        '{p.nombre_comercial}'  (score: {score:.2f}) — sin cambios")
                skipped += 1

        if not DRY_RUN:
            db.commit()
            print(f"\nOK — {updated} proyectos actualizados, {skipped} sin cambios, {no_match} sin match.")
        else:
            print(f"\n[DRY-RUN] — {updated} se actualizarían, {skipped} sin cambios, {no_match} sin match.")

        if no_match_list:
            print(f"\nSin match ({len(no_match_list)}):")
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
