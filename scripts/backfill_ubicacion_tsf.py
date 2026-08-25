"""
Backfill de Proyecto.departamento/municipio/codigo_tsf desde el listado en
vivo de Sun Factory (TSF), para proyectos que no tienen ninguno de los tres.

El sync periodico (sync_tsf_projects, cada 6h) ya rellena estos campos de
forma continua, pero SOLO para proyectos ya vinculados por ID
(sunfactory_project_id/origina_code/codigo_tsf/base_name). Este script cubre
ademas los que solo se pueden encontrar por nombre, con el mismo umbral
estricto (0.95) que el backfill de sub_project de Unergy.
Nunca sobreescribe un valor ya cargado.

Uso:
    python scripts/backfill_ubicacion_tsf.py            # DRY-RUN: solo muestra
    python scripts/backfill_ubicacion_tsf.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.tsf_sync import backfill_ubicacion_codigo_tsf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_ubicacion_codigo_tsf(db, apply=args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill departamento/municipio/codigo_tsf (Sun Factory) -- {modo} ===")
        print(f"Proyectos revisados (con algun campo vacio): {res['revisados']}")

        asignados = res["asignados"]
        print(f"\n-- Asignados ({len(asignados)}): --")
        for a in asignados:
            print(f"  [{a['proyecto_id']:>5}] {a['nombre']:<45} -> {a['cambios']}")

        sin_match = res["sin_match_seguro"]
        print(f"\n-- Sin match seguro ({len(sin_match)}): --")
        for s in sin_match:
            print(f"  [{s['proyecto_id']:>5}] {s['nombre']:<45} ({s['motivo']})")

        if not args.apply and asignados:
            print("\nEsto fue un DRY-RUN -- nada se guardo. Corre con --apply para persistir.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
