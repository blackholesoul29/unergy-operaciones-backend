"""
Backfill de Proyecto.project_id_solarview emparejando por nombre contra
SolarViewClient.get_company_projects().

A diferencia de project_id_solenium, esta columna no tiene ningun mecanismo
de escritura automatica -- solo se puede poblar a mano por SQL directo. Se
empareja por nombre (umbral 0.95) y se asigna el vinculo. Nunca sobreescribe
un valor ya cargado.

Uso:
    python scripts/backfill_project_id_solarview.py            # DRY-RUN: solo muestra
    python scripts/backfill_project_id_solarview.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.proyectos_backfill_solarview import backfill_project_id_solarview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_project_id_solarview(db, apply=args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill project_id_solarview -- {modo} ===")
        print(f"Proyectos revisados (sin project_id_solarview): {res['revisados']}")

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
