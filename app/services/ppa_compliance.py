"""
Servicio de cumplimiento PPA: MWh comprometidos vs. generados.

Calcula el KPI de "Cumplimiento PPA" a nivel de proyecto y de flota usando
únicamente datos de la base de datos (sin llamar a la API externa de Unergy),
por lo que es rápido y apto para consumo directo desde el frontend.

Fuentes de datos (tablas existentes):
- Compromiso (target): ``ppa_compromisos_energia.energia_minima`` por contrato/mes.
  Un proyecto se enlaza a un contrato vía GESCON (``asic_solicitudes``) con un
  ``porcentaje_despacho``; el target del proyecto es la suma de
  ``energia_minima × porcentaje_despacho`` de los contratos de venta a los que
  está asignado en el mes.
- Generación real (actual): suma de ``generacion_diaria.kwh_real`` del proyecto
  en el mes (kWh → MWh).

La resolución GESCON reutiliza ``_resolve_gescon`` / ``_contratos_vigentes`` del
endpoint de cumplimiento (import diferido para evitar import circular).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session


class PPAComplianceService:
    """Calcula cumplimiento PPA (comprometido vs. generado) por proyecto y flota."""

    def __init__(self, db: Session):
        self.db = db

    # ── Helpers de cálculo puro (sin DB, fáciles de testear) ──────────────────

    @staticmethod
    def compute_compliance(
        target_mwh: float | None, actual_mwh: float | None
    ) -> tuple[float | None, float | None]:
        """
        Devuelve ``(delta_mwh, compliance_pct)`` a partir del compromiso y la
        generación real.

        - ``delta_mwh = actual - target`` (positivo = excedente, negativo = déficit).
        - ``compliance_pct = actual / target × 100`` redondeado a 2 decimales.
        - Si no hay target definido (PPA inexistente) → ``(None, None)``.
        - Si el target es 0 → delta calculado pero ``compliance_pct = None``
          (no se puede dividir por cero).
        """
        if target_mwh is None:
            return None, None
        actual = actual_mwh or 0.0
        delta = round(actual - target_mwh, 3)
        pct = round(actual / target_mwh * 100, 2) if target_mwh > 0 else None
        return delta, pct

    @staticmethod
    def aggregate_fleet(rows: list[dict]) -> dict:
        """
        Agrega filas de cumplimiento por proyecto en un resumen de flota.

        Solo los proyectos con PPA definido (``has_ppa``) suman a los totales.
        Función pura: recibe la lista ya calculada y no toca la base de datos.
        """
        con_ppa = [r for r in rows if r.get("has_ppa")]
        total_target = round(sum(r["target_mwh"] for r in con_ppa), 3)
        total_actual = round(sum((r["actual_mwh"] or 0.0) for r in con_ppa), 3)
        total_delta = round(total_actual - total_target, 3)
        fleet_pct = round(total_actual / total_target * 100, 2) if total_target > 0 else None
        return {
            "total_target_mwh": total_target,
            "total_actual_mwh": total_actual,
            "total_delta_mwh": total_delta,
            "fleet_compliance_pct": fleet_pct,
            "n_proyectos": len(rows),
            "n_con_ppa": len(con_ppa),
        }

    # ── Acceso a datos ────────────────────────────────────────────────────────

    def _get_actual_generation(self, project_id: int, year: int, month: int) -> float:
        """Generación real del proyecto en el mes (MWh), 0.0 si no hay datos."""
        return self._get_all_generation(year, month).get(project_id, 0.0)

    def _get_all_generation(self, year: int, month: int) -> dict[int, float]:
        """Generación real (MWh) por proyecto para el mes — una sola query."""
        rows = self.db.execute(text("""
            SELECT proyecto_id, SUM(kwh_real) / 1000.0 AS mwh
            FROM generacion_diaria
            WHERE EXTRACT(YEAR FROM fecha) = :year
              AND EXTRACT(MONTH FROM fecha) = :month
              AND kwh_real IS NOT NULL
            GROUP BY proyecto_id
        """), {"year": year, "month": month}).fetchall()
        return {int(r.proyecto_id): round(float(r.mwh), 3) for r in rows if r.mwh is not None}

    def _build_targets_map(self, year: int, month: int) -> dict[int, float]:
        """
        Compromiso PPA (MWh, ``energia_minima``) por proyecto para el mes.

        Recorre los contratos de venta vigentes, resuelve sus plantas activas vía
        GESCON e imputa ``energia_minima × porcentaje_despacho`` a cada proyecto.
        Las asignaciones duplicadas (exposición en bolsa) no cuentan como target.
        """
        # Import diferido: app.api.v1.cumplimiento importa este servicio.
        from app.api.v1.cumplimiento import _contratos_vigentes, _resolve_gescon
        from app.models.contratos import PPACompromisoEnergia

        compromisos = {
            c.contrato_id: c
            for c in self.db.query(PPACompromisoEnergia).filter(
                PPACompromisoEnergia.año == year,
                PPACompromisoEnergia.mes == month,
            ).all()
        }

        targets: dict[int, float] = defaultdict(float)
        for c in _contratos_vigentes(self.db, year, month):
            if (c.tipo_contrato or "venta") == "compra":
                continue
            comp = compromisos.get(c.id)
            if comp is None or comp.energia_minima is None or not c.numero_codigo_contrato:
                continue
            energia_minima = float(comp.energia_minima)
            for asic in _resolve_gescon(self.db, c.numero_codigo_contrato, year, month):
                if asic.es_duplicado or not asic.proyecto_id:
                    continue
                pct = float(asic.porcentaje_despacho or 0)
                targets[asic.proyecto_id] += energia_minima * pct

        return {pid: round(v, 3) for pid, v in targets.items()}

    def _get_ppa_targets(self, project_id: int, year: int, month: int) -> float | None:
        """Compromiso PPA del proyecto en el mes, o ``None`` si no tiene PPA."""
        return self._build_targets_map(year, month).get(project_id)

    # ── Cálculo por proyecto / flota ──────────────────────────────────────────

    def _row(self, project_id: int, target: float | None, actual: float, *,
             nombre: str | None = None) -> dict:
        delta, pct = self.compute_compliance(target, actual)
        row = {
            "project_id": project_id,
            "target_mwh": target,
            "actual_mwh": round(actual, 3),
            "delta_mwh": delta,
            "compliance_pct": pct,
            "has_ppa": target is not None,
        }
        if nombre is not None:
            row["nombre"] = nombre
        return row

    def calculate_project_compliance(self, project_id: int, year: int, month: int) -> dict:
        """Cumplimiento PPA de un proyecto específico para un mes."""
        from app.models.proyectos import Proyecto

        proyecto = self.db.query(Proyecto).filter(Proyecto.id == project_id).first()
        nombre = proyecto.nombre_comercial if proyecto else None
        target = self._get_ppa_targets(project_id, year, month)
        actual = self._get_actual_generation(project_id, year, month)
        row = self._row(project_id, target, actual, nombre=nombre)
        row["year"] = year
        row["month"] = month
        return row

    def calculate_fleet_compliance(self, year: int, month: int) -> dict:
        """Cumplimiento PPA agregado de la flota más el desglose por proyecto."""
        from app.models.proyectos import Proyecto, EstadoProyectoEnum, TipoProyectoEnum

        proyectos = (
            self.db.query(Proyecto)
            .filter(
                Proyecto.estado == EstadoProyectoEnum.en_operacion,
                Proyecto.tipo_proyecto != TipoProyectoEnum.autoconsumo,
            )
            .order_by(Proyecto.nombre_comercial)
            .all()
        )

        targets = self._build_targets_map(year, month)
        generacion = self._get_all_generation(year, month)

        rows = [
            self._row(
                p.id,
                targets.get(p.id),
                generacion.get(p.id, 0.0),
                nombre=p.nombre_comercial,
            )
            for p in proyectos
        ]
        # Proyectos con compromiso PPA pero fuera del filtro de flota (p.ej. no
        # marcados en_operacion) — inclúyelos para no perder su target.
        seen = {p.id for p in proyectos}
        for pid, target in targets.items():
            if pid not in seen:
                rows.append(self._row(pid, target, generacion.get(pid, 0.0)))

        summary = self.aggregate_fleet(rows)
        summary["year"] = year
        summary["month"] = month
        summary["proyectos"] = rows
        return summary
