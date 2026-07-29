"""
Backfill de la FECHA DE REGISTRO ASIC de las fronteras ya existentes.

Copia el `init_date` que trae Quoia (por `frt_code`) a `fronteras.fecha_registro_asic`
para las fronteras que se crearon antes de que `confirmar_frontera_quoia` empezara
a guardar este dato automaticamente (2026-07-28). Por defecto solo toca fronteras
con la fecha en NULL (no sobreescribe una fecha ya diligenciada a mano).

Uso:
    python scripts/backfill_fecha_registro_asic.py            # DRY-RUN: solo muestra
    python scripts/backfill_fecha_registro_asic.py --apply    # aplica y commitea
    python scripts/backfill_fecha_registro_asic.py --apply --force  # recalcula todas
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.fronteras_backfill_registro_asic import backfill_fecha_registro_asic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    parser.add_argument("--force", action="store_true", help="Recalcula tambien las que ya tienen fecha")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_fecha_registro_asic(db, apply=args.apply, force=args.force)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribio)"
        print(f"\n=== Backfill fecha_registro_asic -- {modo} ===")
        print(f"Fronteras revisadas: {res['revisadas']}")

        actualizadas = res["actualizadas"]
        print(f"\n-- Fechas encontradas ({len(actualizadas)}): --")
        for a in actualizadas:
            prev = f" (antes: {a['anterior']})" if a["anterior"] else ""
            print(f"  [{a['id']:>5}] {a['codigo']:<14} {a['nombre']:<40} -> {a['fecha']}{prev}")

        sin_match = res["sin_match"]
        print(f"\n-- Sin match en Quoia ({len(sin_match)}): --")
        for s in sin_match:
            print(f"  [{s['id']:>5}] {s['codigo']:<14} {s['nombre']:<40} ({s['motivo']})")

        if not args.apply and actualizadas:
            print("\nEsto fue un DRY-RUN -- nada se guardo. Corre con --apply para persistir.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
