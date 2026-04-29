"""
Actualiza srv_representacion, srv_cgm y srv_operacion en proyectos.

Uso:
    python scripts/cargar_servicios.py [DATABASE_URL] [--dry-run] [--force]
"""
import os
import sys
import unicodedata
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
# Datos: (nombre_referencia, representacion, cgm, operacion)
# None en operacion = no modificar
# ---------------------------------------------------------------------------
REFERENCIA = [
    ("Parque solar GD-NAOS 1",                                       True,  True,  None),
    ("GD NAOS 2",                                                     True,  True,  None),
    ("Parque solar Marimonda",                                        True,  True,  None),
    ("Proyecto Bayunca I",                                            True,  False, None),
    ("GD NAOS 3",                                                     True,  True,  None),
    ("GD DELTA 1",                                                    True,  True,  None),
    ("GD POLARIS 1",                                                  True,  True,  None),
    ("Planta Solar Flotante Yurbaqua",                                True,  True,  None),
    ("GD SIRIUS",                                                     True,  True,  None),
    ("GD BIOSOLAR",                                                   True,  True,  None),
    ("GD ASTROLUMEN LA GARITA",                                       True,  True,  None),
    ("GD AGUSTÍN 1",                                                  True,  True,  None),
    ("GD 1MVA SAN ONOFRE",                                            True,  False, None),
    ("YUAN SOLAR",                                                    True,  True,  None),
    ("GD POLARIS 2",                                                  True,  True,  None),
    ("GD DELTA 2",                                                    True,  True,  None),
    ("Sol Y Cielo 7 Los Bongos",                                      True,  True,  None),
    ("CATEDRAL",                                                      True,  True,  None),
    ("GD SAN PELAYO",                                                 True,  True,  None),
    ("Granja 9 Cienaga",                                              True,  True,  None),
    ("MiniGranja 0001 - Uruaco",                                      True,  True,  None),
    ("MiniGranja 0004 - Valle de Gandalf",                            True,  True,  None),
    ("MiniGranja 0005 - Cañahuate",                                   True,  True,  None),
    ("MiniGranja 0006 - Perijá (La inglesa)",                         True,  True,  None),
    ("MiniGranja 0007 - La Paz Vallenata (Medardo)",                  True,  True,  None),
    ("MiniGranja 0008 - La Paz Verso (Villa Sonia)",                  True,  True,  None),
    ("MiniGranja 0009 - El Molino (Macedonia)",                       True,  True,  None),
    ("MiniGranja 0010 - Villanueva (los suspiros)",                   True,  True,  None),
    ("MiniGranja 0013 - La Mesa (La Virginia 1)",                     True,  True,  None),
    ("MiniGranja 0014 - El Olimpo",                                   True,  True,  None),
    ("Minigranja 0016 - La Puya - Valledupar, Cesar (Jericó 4_Cesar)", True, True, None),
    ("MiniGranja 0017 - La Paz Esmeralda - La Esmeralda 1",          True,  True,  None),
    ("Minigranja 0021 - Ibirico",                                     True,  True,  None),
    ("Minigranja 0040 - La Cacica",                                   True,  True,  None),
    ("Minigranja 0041  - Las piloneras",                              True,  True,  None),
    ("Minigranja 0075 - Chiriguaná Norte 2",                          True,  True,  None),
    ("Minigranja 0077 - Chiriguaná Norte 4",                          True,  True,  None),
    ("MiniGranja 0025 - El Copey Occidente",                          True,  True,  None),
    ("Minigranja 0018 - La Paz Leyenda",                              True,  True,  None),
    ("MiniGranja 0019 - El Merengue (Jericó 2_Cesar)",               True,  True,  None),
    ("Minigranja 0022 - La Cumbia",                                   True,  True,  None),
    ("MiniGranja 0024 - San Diego Sur",                               True,  True,  None),
    ("Minigranja 0026 - Valencia Oriente",                            True,  True,  None),
    ("Minigranja 0027 - Valencia Oriente 2",                          True,  True,  None),
    ("Minigranja 0015 - El Son",                                      True,  True,  None),
    ("Minigranja 0002 - Baraya",                                      True,  True,  None),
    ("Minigranja 0012 - La Reserva",                                  True,  True,  None),
]

SIMILARITY_THRESHOLD = 0.60


def norm(s: str) -> str:
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def best_match(ref_name: str, proyectos: list):
    best_p, best_score = None, 0.0
    for p in proyectos:
        s = similarity(ref_name, p.nombre_comercial)
        if s > best_score:
            best_score = s
            best_p = p
    if best_score >= SIMILARITY_THRESHOLD:
        return best_p, best_score
    return None


def bool_str(v):
    return "Sí" if v else "No"


def main():
    tag = f"{'[DRY-RUN] ' if DRY_RUN else ''}{'[FORCE] ' if FORCE else ''}"
    print(f"\n{tag}Actualizando servicios (representación / CGM / operación)...\n")

    db = Session()
    try:
        proyectos = db.query(Proyecto).order_by(Proyecto.nombre_comercial).all()
        print(f"  {len(proyectos)} proyectos en BD\n")

        updated = skipped = no_match = 0
        no_match_list = []

        for ref_name, rep, cgm, oper in REFERENCIA:
            result = best_match(ref_name, proyectos)
            if not result:
                print(f"  NO-MATCH  '{ref_name}'")
                no_match += 1
                no_match_list.append(ref_name)
                continue

            p, score = result
            changes = []

            if p.srv_representacion != rep and (not p.srv_representacion or FORCE):
                changes.append(f"srv_representacion: {bool_str(p.srv_representacion)} → {bool_str(rep)}")
                if not DRY_RUN:
                    p.srv_representacion = rep

            if p.srv_cgm != cgm and (not p.srv_cgm or FORCE):
                changes.append(f"srv_cgm:            {bool_str(p.srv_cgm)} → {bool_str(cgm)}")
                if not DRY_RUN:
                    p.srv_cgm = cgm

            if oper is not None and p.srv_operacion != oper and (not p.srv_operacion or FORCE):
                changes.append(f"srv_operacion:      {bool_str(p.srv_operacion)} → {bool_str(oper)}")
                if not DRY_RUN:
                    p.srv_operacion = oper

            if changes:
                print(f"  UPDATE  '{p.nombre_comercial}'  (ref: '{ref_name}', score: {score:.2f})")
                for c in changes:
                    print(f"          {c}")
                updated += 1
            else:
                print(f"  OK      '{p.nombre_comercial}'  (score: {score:.2f}) — sin cambios")
                skipped += 1

        if not DRY_RUN:
            db.commit()
            print(f"\nOK — {updated} actualizados, {skipped} sin cambios, {no_match} sin match.")
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
