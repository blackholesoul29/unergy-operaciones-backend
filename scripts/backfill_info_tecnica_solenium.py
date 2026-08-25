"""
Backfill de info tecnica (capacidad instalada, voltaje, operador de red,
paneles, inversores) desde SoleniumClient.get_project_detail().

Solo trae datos reales para proyectos tipo minigranja -- para el resto
(autoconsumo/GD/comercial) Solenium no tiene esta info diligenciada.
Si el proyecto ya tiene project_id_solenium, se usa ese vinculo directo; si
no, se empareja por nombre (umbral 0.95) y se asigna el vinculo de paso.
Nunca sobreescribe un valor ya cargado.

Uso:
    python scripts/backfill_info_tecnica_solenium.py            # DRY-RUN: solo muestra
    python scripts/backfill_info_tecnica_solenium.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.proyectos_backfill_solenium import backfill_info_tecnica_solenium


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_info_tecnica_solenium(db, apply=args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill info tecnica (Solenium) -- {modo} ===")
        print(f"Proyectos revisados (sin capacidad_instalada_kwp): {res['revisados']}")

        asignados = res["asignados"]
        print(f"\n-- Asignados ({len(asignados)}): --")
        for a in asignados:
            print(f"  [{a['proyecto_id']:>5}] {a['nombre']:<45} -> {a['cambios']}")

        sin_match = res["sin_match_seguro"]
        print(f"\n-- Sin match seguro / sin datos ({len(sin_match)}): --")
        for s in sin_match:
            print(f"  [{s['proyecto_id']:>5}] {s['nombre']:<45} ({s['motivo']})")

        if not args.apply and asignados:
            print("\nEsto fue un DRY-RUN -- nada se guardo. Corre con --apply para persistir.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
