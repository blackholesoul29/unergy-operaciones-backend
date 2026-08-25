"""
Backfill de Proyecto.fecha_entrada_operacion (COD) desde el listado en vivo
de la plataforma Unergy original.

Si el proyecto ya tiene sub_project, busca el registro de Unergy por
nombre_topico exacto (sin ambigüedad); si no, usa el mismo emparejamiento
difuso y umbral (0.95) que el backfill de sub_project.
Nunca sobreescribe una fecha ya cargada (el query solo mira proyectos con
el campo en NULL).

Uso:
    python scripts/backfill_fecha_entrada_operacion_unergy.py            # DRY-RUN: solo muestra
    python scripts/backfill_fecha_entrada_operacion_unergy.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.proyectos_backfill_unergy import backfill_fecha_entrada_operacion_unergy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_fecha_entrada_operacion_unergy(db, apply=args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill fecha_entrada_operacion (Unergy) -- {modo} ===")
        print(f"Proyectos revisados (sin fecha_entrada_operacion): {res['revisados']}")

        asignados = res["asignados"]
        print(f"\n-- Asignados ({len(asignados)}): --")
        for a in asignados:
            print(f"  [{a['proyecto_id']:>5}] {a['nombre']:<45} -> {a['fecha_entrada_operacion']}")

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
