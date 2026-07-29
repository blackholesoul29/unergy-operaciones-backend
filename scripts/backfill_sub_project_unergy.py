"""
Backfill del API ID Unergy (Proyecto.sub_project) por emparejamiento de nombre
contra el listado en vivo de la plataforma Unergy.

Solo asigna cuando el match es CASI EXACTO (score >= 0.95) -- sin paso de
confirmacion manual, a proposito: mejor dejarlo sin asignar que asignar mal.
Nunca sobreescribe un sub_project ya existente (el query solo mira proyectos
con el campo en NULL).

Uso:
    python scripts/backfill_sub_project_unergy.py            # DRY-RUN: solo muestra
    python scripts/backfill_sub_project_unergy.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.proyectos_backfill_unergy import backfill_sub_project_unergy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_sub_project_unergy(db, apply=args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill API ID Unergy (sub_project) -- {modo} ===")
        print(f"Proyectos revisados (sin sub_project): {res['revisados']}")

        asignados = res["asignados"]
        print(f"\n-- Asignados ({len(asignados)}): --")
        for a in asignados:
            print(f"  [{a['proyecto_id']:>5}] {a['nombre']:<45} -> {a['topico']:<22} "
                  f"(score={a['score']:.2f}, {a['unergy_nombre']!r})")

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
