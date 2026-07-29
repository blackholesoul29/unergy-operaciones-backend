"""
Backfill histórico de páginas sin match del split O&M (OMPaginaSinMatch).

Re-corre la detección de "sin match" sobre las facturas consolidadas de
Mantenimiento ya guardadas (OMFacturaMensual) para las que nunca se persistió
esa información (antes del fix, solo vivía en la respuesta HTTP del upload).
NO toca OMDocumentoProyecto de meses ya facturados — solo puebla la tabla de
pendientes para que se puedan revisar/asignar manualmente desde Proveedor.

Limitación: usa los contratos de mantenimiento ACTUALES, no los que existían
en la fecha del upload original — es una aproximación, no una reconstrucción
exacta (ver docstring de app/services/om_backfill_sin_match.py).

Uso:
    python scripts/backfill_om_sin_match.py            # DRY-RUN: solo muestra
    python scripts/backfill_om_sin_match.py --apply    # aplica y commitea
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.om_backfill_sin_match import backfill_sin_match


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_sin_match(db, apply=args.apply)

        modo = "APLICADO" if args.apply else "DRY-RUN (no se escribió)"
        print(f"\n=== Backfill sin_match O&M — {modo} ===")
        print(f"Períodos revisados: {len(res['periodos_revisados'])} -> {res['periodos_revisados']}")
        print(f"Períodos saltados (ya tenían sin_match registrado): {len(res['periodos_saltados_ya_tenian'])}"
              f" -> {res['periodos_saltados_ya_tenian']}")
        if res["periodos_sin_archivo"]:
            print(f"Períodos SIN archivo en disco (no se pudieron revisar): {res['periodos_sin_archivo']}")

        nuevos = res["nuevos_sin_match"]
        print(f"\n-- Páginas sin match encontradas ({len(nuevos)}): --")
        for n in nuevos:
            print(f"  [{n['periodo']}] pág.{n['pagina']:>2}  {n['razon']:<40}"
                  f"  nombre_extraido={n.get('nombre_extraido')!r}")

        if not args.apply and nuevos:
            print("\nEsto fue un DRY-RUN — nada se guardó. Corre con --apply para persistir.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
