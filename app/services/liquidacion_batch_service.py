"""Lote mensual de borradores de liquidación.

Genera un borrador (`estado='iniciada'`) por cada proyecto en operación que tenga
un contrato PPA, tomando la generación del mes y la tarifa PPA vigente para
estimar los ingresos por energía. Es idempotente: la unicidad
`(proyecto_id, periodo)` de `liquidaciones` evita duplicados, así que re-ejecutar
el lote para el mismo período no crea filas repetidas — simplemente las omite.

El "borrador" reutiliza el modelo `Liquidacion` existente (no un estado nuevo):
`estado='iniciada'` es el estado inicial del flujo manual, y
`fecha_creacion_automatica` marca las filas que produjo este job.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.liquidaciones import Liquidacion
from app.models.proyectos import Proyecto
from app.models.contratos import PPAContrato, PPATarifa
from app.models.usuarios import Usuario

logger = logging.getLogger(__name__)


def _first_of_next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


class LiquidacionBatchService:
    """Crea borradores de liquidación en lote para un mes/año dado."""

    def create_monthly_liquidations(self, db: Session, month: int, year: int) -> list[dict]:
        if not (1 <= month <= 12):
            raise ValueError("month debe estar entre 1 y 12")
        if year < 2000 or year > 2100:
            raise ValueError("year fuera de rango razonable")

        periodo = date(year, month, 1)
        periodo_fin = _first_of_next_month(periodo)  # exclusivo

        generado_por_id = self._resolver_usuario_sistema(db)
        if generado_por_id is None:
            logger.error(
                "[liquidacion_batch] No hay usuario activo (admin/liquidaciones) "
                "para asignar como generado_por — no se puede crear ningún borrador."
            )
            return []

        ahora = datetime.now()
        resultados: list[dict] = []
        procesados: set[int] = set()  # un proyecto puede estar en varios PPA

        contratos = (
            db.query(PPAContrato)
            .filter(PPAContrato.deleted_at.is_(None))
            .options(selectinload(PPAContrato.proyectos))
            .all()
        )

        for contrato in contratos:
            for proyecto in contrato.proyectos:
                if proyecto.id in procesados:
                    continue
                if proyecto.deleted_at is not None or proyecto.estado != "en_operacion":
                    continue
                procesados.add(proyecto.id)

                res = self._crear_borrador(
                    db,
                    proyecto=proyecto,
                    contrato=contrato,
                    periodo=periodo,
                    periodo_fin=periodo_fin,
                    month=month,
                    year=year,
                    generado_por_id=generado_por_id,
                    ahora=ahora,
                )
                resultados.append(res)

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("[liquidacion_batch] commit final falló")
            raise

        creados = sum(1 for r in resultados if r["status"] == "created")
        omitidos = sum(1 for r in resultados if r["status"] == "skipped_existing")
        errores = sum(1 for r in resultados if r["status"] == "error")
        logger.info(
            "[liquidacion_batch] período %04d-%02d: %d creados, %d omitidos (ya existían), "
            "%d errores, %d proyectos evaluados",
            year, month, creados, omitidos, errores, len(resultados),
        )
        return resultados

    # ── internos ────────────────────────────────────────────────────────────────

    def _resolver_usuario_sistema(self, db: Session) -> int | None:
        """Primer usuario activo con rol admin/liquidaciones (mismo criterio que el
        auto-alta de fallas: el job no tiene un usuario de sesión propio)."""
        u = (
            db.query(Usuario.id)
            .filter(Usuario.activo.is_(True), Usuario.rol.in_(("admin", "liquidaciones")))
            .order_by(Usuario.id)
            .first()
        )
        if u is None:
            u = (
                db.query(Usuario.id)
                .filter(Usuario.activo.is_(True))
                .order_by(Usuario.id)
                .first()
            )
        return u[0] if u else None

    def _crear_borrador(self, db, *, proyecto, contrato, periodo, periodo_fin,
                        month, year, generado_por_id, ahora) -> dict:
        base = {
            "proyecto_id": proyecto.id,
            "proyecto_nombre": proyecto.nombre_comercial,
            "periodo": periodo.isoformat(),
            "contrato_ppa_id": contrato.id,
        }

        # Idempotencia: la unicidad es (proyecto_id, periodo) sobre TODAS las filas
        # (incluidas soft-deleted), así que se consulta sin filtrar deleted_at.
        existente = (
            db.query(Liquidacion.id)
            .filter(Liquidacion.proyecto_id == proyecto.id, Liquidacion.periodo == periodo)
            .first()
        )
        if existente:
            logger.info(
                "[liquidacion_batch] omitido: ya existe liquidación %s para proyecto %s (%s) período %s",
                existente[0], proyecto.id, proyecto.nombre_comercial, periodo,
            )
            return {**base, "status": "skipped_existing", "liquidacion_id": existente[0]}

        energia_kwh = self._energia_del_mes(db, proyecto.id, periodo, periodo_fin)
        tarifa = self._tarifa_ppa(db, contrato.id, year, month)
        ingresos = None
        if tarifa is not None:
            ingresos = (Decimal(str(energia_kwh)) * Decimal(str(tarifa))).quantize(Decimal("0.01"))

        liq = Liquidacion(
            proyecto_id=proyecto.id,
            generado_por_id=generado_por_id,
            periodo=periodo,
            tipo_venta="ppa",
            estado="iniciada",
            ingresos_energia_cop=ingresos,
            fecha_creacion_automatica=ahora,
        )
        try:
            with db.begin_nested():
                db.add(liq)
                db.flush()
        except IntegrityError:
            # Carrera con otro proceso / lote: la restricción única lo resolvió.
            logger.warning(
                "[liquidacion_batch] IntegrityError creando borrador proyecto %s período %s — omitido",
                proyecto.id, periodo,
            )
            return {**base, "status": "skipped_existing", "liquidacion_id": None}
        except Exception:
            logger.exception(
                "[liquidacion_batch] error creando borrador proyecto %s período %s",
                proyecto.id, periodo,
            )
            return {**base, "status": "error", "liquidacion_id": None}

        logger.info(
            "[liquidacion_batch] creado borrador %s proyecto %s (%s) período %s: %.3f kWh, ingresos=%s",
            liq.id, proyecto.id, proyecto.nombre_comercial, periodo, float(energia_kwh),
            ingresos if ingresos is not None else "sin tarifa",
        )
        return {
            **base,
            "status": "created",
            "liquidacion_id": liq.id,
            "energia_kwh": float(energia_kwh),
            "tarifa_ppa": float(tarifa) if tarifa is not None else None,
            "ingresos_energia_cop": float(ingresos) if ingresos is not None else None,
        }

    def _energia_del_mes(self, db, proyecto_id, periodo, periodo_fin) -> float:
        from app.models.generacion import GeneracionDiaria

        total = (
            db.query(func.coalesce(func.sum(GeneracionDiaria.kwh_real), 0))
            .filter(
                GeneracionDiaria.proyecto_id == proyecto_id,
                GeneracionDiaria.fecha >= periodo,
                GeneracionDiaria.fecha < periodo_fin,
            )
            .scalar()
        )
        return float(total or 0)

    def _tarifa_ppa(self, db, contrato_id, year, month) -> float | None:
        row = (
            db.query(PPATarifa.tarifa)
            .filter(
                PPATarifa.contrato_id == contrato_id,
                PPATarifa.año == year,
                PPATarifa.mes == month,
            )
            .first()
        )
        if row and row[0] is not None:
            return float(row[0])
        return None
