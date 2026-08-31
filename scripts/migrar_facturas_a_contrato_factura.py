"""Migracion unica: JSONB facturas_solenium/facturas_inversionistas -> tabla
contrato_factura (auditoria de "JSON suelto" 2026-08-30).

Dos fuentes, en este orden (la segunda no pisa lo que ya inserto la primera):

1. Lo que ya este cargado en las columnas JSONB de contratos reales (por si
   alguien uso la UI antes de este cambio) -- via SQL crudo, porque el modelo
   ORM ya no mapea esas columnas.
2. Los datasets estaticos que hasta ahora vivian en el frontend como fallback
   (scripts/data/facturas_solenium_2025.json y facturas_inversionistas_2025.json,
   extraidos de facturas_solenium_data.js / facturas_inversionistas_data.js) --
   solo para el proyecto que no tenga ya filas de ese tipo en la BD (paso 1).

Requiere que el proyecto ya tenga un ContratoServicio(servicio_aplica='mantenimiento').
Los que no matcheen quedan listados al final para resolver a mano.

Uso: python scripts/migrar_facturas_a_contrato_factura.py [--aplicar]
Sin --aplicar corre en modo dry-run (solo imprime que haria).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.contratos import ContratoServicio, ContratoFactura
from app.utils.proyecto_matching import find_proyecto_by_name

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _contrato_mantenimiento_id(db, proyecto_id: int) -> int | None:
    row = (
        db.query(ContratoServicio.id)
        .filter(ContratoServicio.proyecto_id == proyecto_id, ContratoServicio.servicio_aplica == "mantenimiento")
        .first()
    )
    return row[0] if row else None


def migrar(aplicar: bool) -> None:
    db = SessionLocal()
    ya_tiene: set[tuple[int, str]] = set()  # (contrato_id, tipo) que YA tiene al menos una fila
    insertadas = 0
    sin_match: list[str] = []

    try:
        # ── Paso 1: lo que ya haya en las columnas JSONB (via SQL crudo) ─────────
        filas_jsonb = db.execute(text(
            "SELECT id, facturas_solenium, facturas_inversionistas FROM contratos_servicio "
            "WHERE facturas_solenium IS NOT NULL OR facturas_inversionistas IS NOT NULL"
        )).fetchall()

        for contrato_id, sol, inv in filas_jsonb:
            for tipo, lista in (("solenium", sol), ("inversionista", inv)):
                for f in (lista or []):
                    if not isinstance(f, dict) or not f.get("fecha"):
                        continue
                    print(f"  [jsonb] contrato={contrato_id} tipo={tipo} fecha={f['fecha']}")
                    if aplicar:
                        db.add(ContratoFactura(
                            contrato_id=contrato_id, tipo=tipo, fecha=f["fecha"],
                            inversionista=f.get("inversionista"), numero_factura=f.get("numero_factura"),
                            monto=f.get("monto"), enlace_soporte=f.get("enlace_soporte"),
                        ))
                    insertadas += 1
                    ya_tiene.add((contrato_id, tipo))
        if aplicar and filas_jsonb:
            db.commit()

        # ── Paso 2: datasets estaticos, solo donde el paso 1 no dejo nada ────────
        proyecto_cache: dict[str, int | None] = {}

        def _resolver_contrato(nombre_proyecto: str) -> int | None:
            if nombre_proyecto not in proyecto_cache:
                proy = find_proyecto_by_name(db, nombre_proyecto)
                proyecto_cache[nombre_proyecto] = proy.id if proy else None
            pid = proyecto_cache[nombre_proyecto]
            return _contrato_mantenimiento_id(db, pid) if pid else None

        with open(os.path.join(_DATA_DIR, "facturas_solenium_2025.json"), encoding="utf-8") as fh:
            sol_data = json.load(fh)
        with open(os.path.join(_DATA_DIR, "facturas_inversionistas_2025.json"), encoding="utf-8") as fh:
            inv_data = json.load(fh)

        for tipo, dataset in (("solenium", sol_data), ("inversionista", inv_data)):
            for f in dataset:
                nombre_proyecto = f["proyecto"]
                contrato_id = _resolver_contrato(nombre_proyecto)
                if contrato_id is None:
                    if nombre_proyecto not in sin_match:
                        sin_match.append(nombre_proyecto)
                    continue
                if (contrato_id, tipo) in ya_tiene:
                    continue  # el paso 1 ya tiene datos reales para este contrato+tipo
                print(f"  [estatico] proyecto={nombre_proyecto!r} -> contrato={contrato_id} tipo={tipo} fecha={f['fecha']}")
                if aplicar:
                    db.add(ContratoFactura(
                        contrato_id=contrato_id, tipo=tipo, fecha=f["fecha"],
                        inversionista=f.get("inversionista"), numero_factura=f.get("numero_factura"),
                        monto=f.get("monto"), enlace_soporte=f.get("enlace_soporte"),
                    ))
                insertadas += 1

        if aplicar:
            db.commit()

        print(f"\n{'Insertadas' if aplicar else 'Se insertarian'}: {insertadas}")
        if sin_match:
            print(f"\nProyectos SIN contrato de mantenimiento (revisar a mano): {len(sin_match)}")
            for n in sin_match:
                print(f"  - {n}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrar(aplicar="--aplicar" in sys.argv)
