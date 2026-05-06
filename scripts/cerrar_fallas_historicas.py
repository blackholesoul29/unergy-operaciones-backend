"""
Cierra todas las fallas de 2024 y 2025 que estén en estado abierto.
Estados afectados: abierta, en_gestion, en_espera  →  cerrada

Uso:
    cd unergy-operaciones-backend
    python scripts/cerrar_fallas_historicas.py [--dry-run]
"""
import sys
import os
from datetime import datetime, date

# Asegurar que el path del proyecto esté en sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.fallas import Falla, FallaCatEstado

ESTADOS_ABIERTOS = {"abierta", "en_gestion", "en_espera"}
DRY_RUN = "--dry-run" in sys.argv


def main():
    db = SessionLocal()
    try:
        # Obtener estado "cerrada"
        estado_cerrada = db.query(FallaCatEstado).filter(FallaCatEstado.codigo == "cerrada").first()
        if not estado_cerrada:
            print("ERROR: No se encontró el estado 'cerrada' en falla_cat_estados.")
            return

        # Estados abiertos
        estados_abiertos = (
            db.query(FallaCatEstado)
            .filter(FallaCatEstado.codigo.in_(ESTADOS_ABIERTOS))
            .all()
        )
        ids_abiertos = [e.id for e in estados_abiertos]
        if not ids_abiertos:
            print("ERROR: No se encontraron estados abiertos.")
            return

        # Fallas 2024-2025 con estado abierto
        fallas = (
            db.query(Falla)
            .filter(
                Falla.estado_id.in_(ids_abiertos),
                Falla.fecha_identificacion >= date(2024, 1, 1),
                Falla.fecha_identificacion <= date(2025, 12, 31),
            )
            .all()
        )

        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Fallas a cerrar: {len(fallas)}\n")
        print(f"{'ID':<12} {'Proyecto':<35} {'Estado actual':<15} {'Fecha'}")
        print("-" * 80)

        for f in fallas:
            estado_actual = f.estado.codigo if f.estado else "?"
            proyecto = (f.proyecto.nombre_comercial if f.proyecto else "Sin proyecto")[:34]
            print(f"{f.codigo_interno or str(f.id):<12} {proyecto:<35} {estado_actual:<15} {f.fecha_identificacion}")

            if not DRY_RUN:
                f.estado_id = estado_cerrada.id
                if not f.fecha_resolucion:
                    f.fecha_resolucion = datetime.now()

        if not DRY_RUN:
            db.commit()
            print(f"\n✓ {len(fallas)} fallas cerradas exitosamente.")
        else:
            print(f"\n[DRY-RUN] Se cerrarían {len(fallas)} fallas. Ejecuta sin --dry-run para aplicar.")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
