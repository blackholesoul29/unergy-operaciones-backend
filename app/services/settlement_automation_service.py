"""
Servicio de automatización de liquidaciones.

Conecta los datos ingeridos del MEM (generación ASIC + precios de bolsa) con el
módulo de liquidaciones, generando pre-liquidaciones (`LiquidacionPreliminar`)
que el equipo revisa y aprueba antes de crear la `Liquidacion` final.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.proyectos import Proyecto
from app.models.mem import MEMDatosASIC, MEMPrecioBolsa, LiquidacionPreliminar
from app.models.cumplimiento import CumplimientoMensual

logger = logging.getLogger(__name__)


def compute_datos_calculados(
    generacion_real_kwh: float,
    horas_con_datos: int,
    precio_promedio_cop_kwh: float | None,
    generacion_esperada_kwh: float | None,
    cumplimiento: dict | None = None,
) -> dict:
    """
    Lógica de negocio pura de la pre-liquidación. Sin dependencia de la BD para
    poder testearla de forma aislada.
    """
    ingreso_estimado_cop = None
    if precio_promedio_cop_kwh is not None:
        ingreso_estimado_cop = round(generacion_real_kwh * precio_promedio_cop_kwh, 2)

    desviacion_pct = None
    if generacion_esperada_kwh:
        desviacion_pct = round(
            (generacion_real_kwh - generacion_esperada_kwh) / generacion_esperada_kwh * 100, 2
        )

    return {
        "fuente": "MEM/ASIC",
        "generacion_real_kwh": round(generacion_real_kwh, 3),
        "generacion_esperada_kwh": (
            round(generacion_esperada_kwh, 3) if generacion_esperada_kwh is not None else None
        ),
        "desviacion_pct": desviacion_pct,
        "horas_con_datos": horas_con_datos,
        "precio_bolsa_promedio_cop_kwh": (
            round(precio_promedio_cop_kwh, 4) if precio_promedio_cop_kwh is not None else None
        ),
        "ingreso_estimado_cop": ingreso_estimado_cop,
        "cumplimiento": cumplimiento,
    }


class SettlementAutomationService:
    def __init__(self, db: Session):
        self.db = db

    def _periodo_bounds(self, year: int, month: int) -> tuple[date, date]:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    def _expected_kwh(self, proyecto: Proyecto, month: int) -> float | None:
        """Generación esperada del mes a partir de la simulación P50 (índice 0 = enero)."""
        serie = getattr(proyecto, "p50_mensual_kwh", None)
        if isinstance(serie, list) and len(serie) >= month:
            try:
                return float(serie[month - 1])
            except (TypeError, ValueError):
                return None
        return None

    def generate_pre_settlements_for_period(self, year: int, month: int) -> dict:
        """
        Genera (o actualiza) una pre-liquidación por cada proyecto en operación
        con datos del MEM para el período indicado.
        """
        periodo_inicio, periodo_fin = self._periodo_bounds(year, month)

        # Precio de bolsa promedio del período (compartido entre proyectos).
        precio_promedio = (
            self.db.query(func.avg(MEMPrecioBolsa.precio_cop_kwh))
            .filter(MEMPrecioBolsa.fecha >= periodo_inicio, MEMPrecioBolsa.fecha <= periodo_fin)
            .scalar()
        )
        precio_promedio = float(precio_promedio) if precio_promedio is not None else None

        proyectos = (
            self.db.query(Proyecto)
            .filter(Proyecto.estado == "en_operacion", Proyecto.deleted_at.is_(None))
            .all()
        )

        creadas = actualizadas = sin_datos = 0
        errores: list[str] = []

        for proyecto in proyectos:
            try:
                agg = (
                    self.db.query(
                        func.coalesce(func.sum(MEMDatosASIC.generacion_kwh), 0.0),
                        func.count(MEMDatosASIC.id),
                    )
                    .filter(
                        MEMDatosASIC.proyecto_id == proyecto.id,
                        MEMDatosASIC.fecha >= periodo_inicio,
                        MEMDatosASIC.fecha <= periodo_fin,
                    )
                    .one()
                )
                generacion_real = float(agg[0] or 0.0)
                horas_con_datos = int(agg[1] or 0)

                if horas_con_datos == 0:
                    sin_datos += 1
                    continue

                cumplimiento_row = (
                    self.db.query(CumplimientoMensual)
                    .filter(
                        CumplimientoMensual.proyecto_id == proyecto.id,
                        CumplimientoMensual.anio == year,
                        CumplimientoMensual.mes == month,
                    )
                    .first()
                )
                cumplimiento = None
                if cumplimiento_row is not None:
                    cumplimiento = {
                        "id": cumplimiento_row.id,
                        "contrato_ppa_id": cumplimiento_row.contrato_ppa_id,
                        "compromiso_mwh": (
                            float(cumplimiento_row.compromiso_mwh)
                            if cumplimiento_row.compromiso_mwh is not None else None
                        ),
                        "gen_total_mwh": (
                            float(cumplimiento_row.gen_total_mwh)
                            if cumplimiento_row.gen_total_mwh is not None else None
                        ),
                        "estado": cumplimiento_row.estado,
                    }

                datos = compute_datos_calculados(
                    generacion_real_kwh=generacion_real,
                    horas_con_datos=horas_con_datos,
                    precio_promedio_cop_kwh=precio_promedio,
                    generacion_esperada_kwh=self._expected_kwh(proyecto, month),
                    cumplimiento=cumplimiento,
                )

                existing = (
                    self.db.query(LiquidacionPreliminar)
                    .filter(
                        LiquidacionPreliminar.proyecto_id == proyecto.id,
                        LiquidacionPreliminar.periodo == periodo_inicio,
                    )
                    .first()
                )
                if existing:
                    # No se pisan pre-liquidaciones ya aprobadas/rechazadas.
                    if existing.estado == "pendiente_revision":
                        existing.datos_calculados = datos
                        actualizadas += 1
                else:
                    self.db.add(LiquidacionPreliminar(
                        proyecto_id=proyecto.id,
                        periodo=periodo_inicio,
                        estado="pendiente_revision",
                        datos_calculados=datos,
                    ))
                    creadas += 1
            except Exception as e:  # noqa: BLE001 — una falla por proyecto no aborta el lote
                errores.append(f"proyecto {proyecto.id}: {e}")

        self.db.commit()

        return {
            "periodo": periodo_inicio,
            "preliminares_creadas": creadas,
            "preliminares_actualizadas": actualizadas,
            "proyectos_sin_datos": sin_datos,
            "errores": errores[:100],
        }
