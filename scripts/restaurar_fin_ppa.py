"""
Restaura el fin contractual (`fecha_fin`) de contratos PPA multi-planta cuya fecha fue
colapsada por el bug de terminación: un proceso de arranque tomaba la terminación de UNA
planta/SIC y la estampaba como fin de TODO el contrato (p. ej. Terpel 1, que corre hasta
2039, quedaba en 2024-08-30 tras terminar una sola de sus 12 plantas).

El fix de código (app/api/v1/asic.py + app/main.py) ya impide que vuelva a ocurrir: el PPA
sólo se termina cuando se cierra su ÚLTIMA planta. Este script repara los datos ya dañados.

Criterio (firma exacta del bug, conservador — no toca nada más):
  1. El contrato AÚN tiene al menos una planta abierta (registro/modificación 'publicado'
     con fecha_fin vacía) → no debería estar terminado.
  2. Su `fecha_fin` actual coincide con la fecha de terminación de alguna de sus plantas
     (es decir, fue colapsado).
  3. Esa fecha es anterior a la cobertura de su tabla de tarifas, que es la fuente intacta
     del fin contractual (el último mes tarifado = fin del contrato).
Se restaura al último día del último mes tarifado. Es idempotente: tras restaurar deja de
cumplir la condición 2/3.

Uso:
    python scripts/restaurar_fin_ppa.py            # DRY-RUN: solo muestra qué cambiaría
    python scripts/restaurar_fin_ppa.py --apply    # aplica y commitea los cambios
"""
import os
import sys
import argparse
import calendar
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models import PPAContrato, AsicSolicitud
from app.models.contratos import PPATarifa
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum

_REGISTRO = [TipoSolicitudAsicEnum.registro, TipoSolicitudAsicEnum.modificacion]


def _fin_contractual_por_tarifas(db, contrato_id: int) -> date | None:
    """Último día del último mes con tarifa cargada para el contrato."""
    fila = (
        db.query(PPATarifa.año, PPATarifa.mes)
        .filter(PPATarifa.contrato_id == contrato_id)
        .order_by(PPATarifa.año.desc(), PPATarifa.mes.desc())
        .first()
    )
    if not fila:
        return None
    año, mes = fila
    return date(año, mes, calendar.monthrange(año, mes)[1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Aplica los cambios (por defecto es dry-run de solo lectura)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        candidatos = []  # (ppa, nueva_fecha)
        ppas = (
            db.query(PPAContrato)
            .filter(PPAContrato.deleted_at.is_(None))
            .all()
        )
        for ppa in ppas:
            if not ppa.numero_codigo_contrato or ppa.fecha_fin is None:
                continue

            registros = (
                db.query(AsicSolicitud)
                .filter(
                    AsicSolicitud.contrato_interno == ppa.numero_codigo_contrato,
                    AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
                    AsicSolicitud.tipo_solicitud.in_(_REGISTRO),
                )
                .all()
            )
            # 1) ¿queda alguna planta abierta? si no, el contrato sí está terminado → no tocar
            if not registros or not any(r.fecha_fin is None for r in registros):
                continue

            # 2) ¿la fecha_fin actual coincide con la terminación de alguna de sus plantas?
            sics = {r.codigo_sic_contrato for r in registros if r.codigo_sic_contrato}
            if not sics:
                continue
            fechas_term = {
                t.fecha_fin
                for t in db.query(AsicSolicitud)
                .filter(
                    AsicSolicitud.tipo_solicitud == TipoSolicitudAsicEnum.terminacion,
                    AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
                    AsicSolicitud.codigo_sic_contrato.in_(sics),
                    AsicSolicitud.fecha_fin.isnot(None),
                )
                .all()
            }
            if ppa.fecha_fin not in fechas_term:
                continue

            # 3) restaurar al fin contractual derivado de las tarifas (si es posterior)
            fin = _fin_contractual_por_tarifas(db, ppa.id)
            if fin is None:
                print(f"  ⚠ {ppa.numero_codigo_contrato}: sin tarifas, no se puede derivar "
                      f"el fin contractual (fecha_fin actual {ppa.fecha_fin}); revisar a mano.")
                continue
            if fin <= ppa.fecha_fin:
                continue

            candidatos.append((ppa, fin))

        if not candidatos:
            print("✓ No hay contratos PPA con la firma del bug. Nada que restaurar.")
            return

        print(f"\n{'[DRY-RUN] ' if not args.apply else ''}Contratos a restaurar:")
        print(f"{'Código':<22}{'Nombre':<28}{'fecha_fin actual':<18}{'→ nueva'}")
        print("-" * 80)
        for ppa, fin in candidatos:
            print(f"{(ppa.numero_codigo_contrato or ''):<22}"
                  f"{(ppa.nombre_interno or ''):<28}"
                  f"{str(ppa.fecha_fin):<18}→ {fin}")
            if args.apply:
                ppa.fecha_fin = fin

        if args.apply:
            db.commit()
            print(f"\n✅ {len(candidatos)} contrato(s) restaurado(s) y guardado(s).")
        else:
            print(f"\n{len(candidatos)} contrato(s) cambiarían. Ejecuta con --apply para guardarlos.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
