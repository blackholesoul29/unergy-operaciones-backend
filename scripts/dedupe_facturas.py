"""Deduplica facturas de servicio repetidas en liquidaciones.

Una factura se considera duplicada si comparte (liquidacion_id, tipo_servicio,
valor_cop) con otra. Se CONSERVA la que tenga soporte adjunto; si ambas o ninguna
tienen soporte, se conserva el id menor.

Uso (desde la raíz del backend, con la DATABASE_URL del entorno apuntando a la BD):
  python scripts/dedupe_facturas.py            # DRY-RUN: solo lista lo que borraría
  python scripts/dedupe_facturas.py --apply    # ejecuta el borrado

Es idempotente: al correrlo de nuevo no encuentra nada que borrar.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine

# Filas duplicadas (las que se borrarían): existe otra "mejor" en su mismo grupo.
_COND = """
  a.id <> b.id
  AND a.liquidacion_id = b.liquidacion_id
  AND a.tipo_servicio = b.tipo_servicio
  AND a.valor_cop = b.valor_cop
  AND (
    ((a.soporte_url IS NULL OR a.soporte_url = '') AND (b.soporte_url IS NOT NULL AND b.soporte_url <> ''))
    OR (
      ((a.soporte_url IS NULL OR a.soporte_url = '') = (b.soporte_url IS NULL OR b.soporte_url = ''))
      AND a.id > b.id
    )
  )
"""

FIND_SQL = f"""
SELECT a.id, a.liquidacion_id, a.tipo_servicio, a.valor_cop, a.soporte_url
FROM liquidacion_facturas a
WHERE EXISTS (SELECT 1 FROM liquidacion_facturas b WHERE {_COND})
ORDER BY a.liquidacion_id, a.tipo_servicio, a.id
"""

DELETE_SQL = f"DELETE FROM liquidacion_facturas a USING liquidacion_facturas b WHERE {_COND}"


def main():
    apply = "--apply" in sys.argv
    with engine.connect() as conn:
        rows = conn.execute(text(FIND_SQL)).fetchall()
        print(f"Facturas de servicio duplicadas detectadas: {len(rows)}")
        for r in rows:
            sop = "con soporte" if r.soporte_url else "SIN soporte"
            print(f"  id={r.id}  liq={r.liquidacion_id}  {r.tipo_servicio}  {r.valor_cop}  ({sop})")
        if not rows:
            print("No hay nada que limpiar.")
            return
        if apply:
            res = conn.execute(text(DELETE_SQL))
            conn.commit()
            print(f"\n✔ Facturas duplicadas eliminadas: {res.rowcount}")
        else:
            print("\nDRY-RUN. Vuelve a ejecutar con --apply para borrar definitivamente.")


if __name__ == "__main__":
    main()
