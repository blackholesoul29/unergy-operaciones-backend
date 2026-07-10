"""
Backfill de la FECHA DE INICIO DE COMERCIALIZACIÓN de los proyectos.

Regla de negocio (sin hardcode): la fecha de inicio de comercialización de una
planta es el PRIMER día calendario (hora Colombia) en que registró generación
real de energía. Se deriva consultando la API de generación de Unergy y se
persiste en proyectos.fecha_inicio_comercializacion.

Es idempotente: sin --force solo toca proyectos con la fecha en NULL que no hayan
sido editados a mano. Al final imprime los proyectos que quedaron SIN fecha (sin
identificador de monitoreo o sin generación registrada) — ese es el reporte que
pide el negocio.

Uso:
    python scripts/backfill_fecha_comercializacion.py            # DRY-RUN: solo muestra
    python scripts/backfill_fecha_comercializacion.py --apply    # aplica y commitea
    python scripts/backfill_fecha_comercializacion.py --apply --force  # recalcula todo
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.services.comercializacion import (
    backfill_comercializacion,
    proyectos_sin_fecha_comercializacion,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplica y commitea (por defecto es dry-run)")
    parser.add_argument("--force", action="store_true", help="Recalcula también los que ya tienen fecha")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        res = backfill_comercializacion(db, force=args.force, dry_run=not args.apply)
        if not res.get("ok"):
            print(f"ERROR: {res.get('error')}")
            return

        modo = "DRY-RUN (no se escribió)" if not args.apply else "APLICADO"
        print(f"\n=== Backfill fecha de comercialización — {modo} ===")
        print(f"Proyectos procesados: {res['procesados']}")

        actualizados = res["actualizados"]
        print(f"\n-- Fechas derivadas ({len(actualizados)}): --")
        for a in actualizados:
            prev = f" (antes: {a['anterior']})" if a["anterior"] else ""
            print(f"  [{a['id']:>4}] {a['nombre']:<45} -> {a['fecha']}  (via {a['identificador']}){prev}")

        sin_gen = res["sin_generacion"]
        print(f"\n-- Sin generación registrada ({len(sin_gen)}): --")
        for s in sin_gen:
            print(f"  [{s['id']:>4}] {s['nombre']:<45} (identificador: {s['identificador']})")

        sin_id = res["sin_identificador"]
        print(f"\n-- Sin identificador de monitoreo ({len(sin_id)}): --")
        for s in sin_id:
            print(f"  [{s['id']:>4}] {s['nombre']}")

        # Reporte final consolidado: TODOS los que siguen sin fecha
        faltantes = proyectos_sin_fecha_comercializacion(db)
        print(f"\n=== PROYECTOS SIN FECHA DE INICIO DE COMERCIALIZACIÓN ({len(faltantes)}) ===")
        for f in faltantes:
            print(f"  [{f['id']:>4}] {f['nombre']:<45} estado={f['estado']:<14} "
                  f"repr={'sí' if f['srv_representacion'] else 'no':<3} motivo={f['motivo']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
