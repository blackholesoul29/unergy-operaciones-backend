"""
Generación automática de borradores de informes operativos.

Agrega datos de monitoreo (``generacion_diaria``), contratos PPA y cumplimiento
(``cumplimiento_mensual``) para producir el HTML y los datos de gráficas de un
informe, que luego se guarda como *borrador* en ``informes_guardados`` y entra al
flujo editorial existente (revisión → aprobación → envío).

Tipos de informe:
  - ``op``   : informe operativo de un proyecto (foco en generación vs. P90, FC).
  - ``fmo``  : informe de un proyecto con foco en cumplimiento PPA y economía.
  - ``port`` : informe consolidado de un portafolio (agrega sus proyectos).

Diseño/testing: el cálculo de KPIs y el armado del HTML/charts son funciones
*puras* (sin BD) — los métodos ``generate_*`` sólo hacen las consultas y delegan
en ellas. Así los KPIs y la validación de huecos de datos se testean con datos
simulados, igual que el resto del repo (ver ``tests/test_cumplimiento.py``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.utils.report_templates import generate_chart_data, render_report

logger = logging.getLogger("report_generator")

# Si falta más de este % de días de generación en el período, el informe NO se
# genera (los KPIs serían poco confiables). Spec: huecos > 5% ⇒ no generar.
MAX_DATA_GAP_PCT = 5.0

_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


class DataGapError(Exception):
    """Se levanta cuando faltan demasiados datos de generación en el período.

    ``code`` es un identificador estable para que la API lo devuelva al cliente.
    """

    code = "DATA_GAP"

    def __init__(self, gap_pct: float, days_with_data: int, days_expected: int,
                 message: str | None = None):
        self.gap_pct = gap_pct
        self.days_with_data = days_with_data
        self.days_expected = days_expected
        super().__init__(
            message
            or (f"Datos de generación insuficientes: faltan {gap_pct:.1f}% de los "
                f"días ({days_with_data}/{days_expected}). Umbral máximo "
                f"{MAX_DATA_GAP_PCT:.0f}%.")
        )


# ── Helpers puros de cálculo de KPIs ─────────────────────────────────────────

def days_in_period(start: date, end: date) -> int:
    """Número de días en [start, end] inclusive (mínimo 0)."""
    return max((end - start).days + 1, 0)


def completeness_pct(days_with_data: int, days_expected: int) -> float:
    """% de días del período que tienen dato de generación."""
    if days_expected <= 0:
        return 0.0
    return min(days_with_data / days_expected * 100.0, 100.0)


def data_gap_pct(days_with_data: int, days_expected: int) -> float:
    """% de días sin dato (complemento de :func:`completeness_pct`)."""
    return round(100.0 - completeness_pct(days_with_data, days_expected), 4)


def validate_completeness(days_with_data: int, days_expected: int,
                          max_gap_pct: float = MAX_DATA_GAP_PCT) -> float:
    """Valida la completitud de datos; levanta :class:`DataGapError` si el hueco
    supera ``max_gap_pct``. Devuelve el gap (%) cuando es aceptable."""
    gap = data_gap_pct(days_with_data, days_expected)
    if gap > max_gap_pct:
        raise DataGapError(gap, days_with_data, days_expected)
    return gap


def capacity_factor_pct(total_kwh: float | None, kwp: float | None,
                        hours: float) -> float | None:
    """Factor de capacidad (%): energía real / energía teórica máxima.

    energía teórica = potencia instalada (kWp) × horas del período.
    """
    if not total_kwh or not kwp or kwp <= 0 or hours <= 0:
        return None
    return round(total_kwh / (kwp * hours) * 100.0, 2)


def performance_index_pct(real_kwh: float | None,
                          expected_kwh: float | None) -> float | None:
    """Índice de desempeño (%): generación real / generación esperada (P90)."""
    if real_kwh is None or not expected_kwh or expected_kwh <= 0:
        return None
    return round(real_kwh / expected_kwh * 100.0, 2)


def compliance_pct(gen_mwh: float | None,
                   compromiso_mwh: float | None) -> float | None:
    """Cumplimiento PPA (%): generación / compromiso de energía."""
    if gen_mwh is None or not compromiso_mwh or compromiso_mwh <= 0:
        return None
    return round(gen_mwh / compromiso_mwh * 100.0, 2)


def _fmt(value: float | None, decimals: int = 1) -> str:
    """Formato de número con separador de miles (es-CO) o '—' si es None."""
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def _last_day_of_month(d: date) -> date:
    """Último día del mes de ``d``."""
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - _one_day()


def periodo_display(start: date, end: date) -> str:
    """Etiqueta legible del período. Un mes calendario completo → 'Mayo 2026';
    en cualquier otro caso, el rango 'inicio — fin'."""
    if (start.year, start.month) == (end.year, end.month) \
            and start.day == 1 and end == _last_day_of_month(start):
        return f"{_MESES_ES[start.month - 1].capitalize()} {start.year}"
    return f"{start.isoformat()} — {end.isoformat()}"


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


# ── Estructuras de agregados (entrada de los builders puros) ──────────────────

@dataclass
class DailyPoint:
    fecha: str
    kwh_real: float | None = None
    kwh_p90: float | None = None


@dataclass
class ComplianceRow:
    contrato: str
    gen_mwh: float | None = None
    compromiso_mwh: float | None = None

    @property
    def cumplimiento_pct(self) -> float | None:
        return compliance_pct(self.gen_mwh, self.compromiso_mwh)


@dataclass
class ProjectAggregate:
    proyecto_nombre: str
    sub_project: str
    kwp: float | None
    period_start: date
    period_end: date
    total_kwh: float | None = None
    expected_kwh: float | None = None       # P90 del período
    autoconsumo_kwh: float | None = None
    days_with_data: int = 0
    daily: list[DailyPoint] = field(default_factory=list)
    compliance: list[ComplianceRow] = field(default_factory=list)

    @property
    def days_expected(self) -> int:
        return days_in_period(self.period_start, self.period_end)


@dataclass
class PortfolioMember:
    nombre: str
    total_kwh: float | None
    expected_kwh: float | None
    kwp: float | None
    days_with_data: int
    days_expected: int


@dataclass
class PortfolioAggregate:
    nombre: str
    sub_project: str
    period_start: date
    period_end: date
    members: list[PortfolioMember] = field(default_factory=list)


# ── Builders puros (agregado → {html, charts, kpis}) ─────────────────────────

def build_project_report(report_type: str, agg: ProjectAggregate,
                         max_gap_pct: float = MAX_DATA_GAP_PCT) -> dict:
    """Construye el informe de un proyecto (op/fmo). Valida huecos de datos
    (levanta :class:`DataGapError`) y devuelve ``{html_content, charts_data,
    kpis, gap_pct, periodo_display}``."""
    gap = validate_completeness(agg.days_with_data, agg.days_expected, max_gap_pct)

    hours = agg.days_expected * 24
    fc = capacity_factor_pct(agg.total_kwh, agg.kwp, hours)
    pi = performance_index_pct(agg.total_kwh, agg.expected_kwh)
    comp_global = (
        sum(c.gen_mwh or 0 for c in agg.compliance),
        sum(c.compromiso_mwh or 0 for c in agg.compliance),
    )
    cumpl = compliance_pct(comp_global[0] or None, comp_global[1] or None)

    kpis = [
        {"label": "Generación", "value": _fmt(agg.total_kwh), "unit": "kWh"},
        {"label": "Esperado (P90)", "value": _fmt(agg.expected_kwh), "unit": "kWh"},
        {"label": "Índice desempeño", "value": _fmt(pi, 1), "unit": "%"},
        {"label": "Factor de capacidad", "value": _fmt(fc, 2), "unit": "%"},
        {"label": "Completitud datos",
         "value": _fmt(completeness_pct(agg.days_with_data, agg.days_expected), 1),
         "unit": "%"},
    ]
    if report_type == "fmo":
        kpis.append({"label": "Cumplimiento PPA", "value": _fmt(cumpl, 1), "unit": "%"})

    secciones = []
    if report_type == "fmo" and agg.compliance:
        secciones.append({
            "titulo": "Cumplimiento PPA",
            "descripcion": "Generación vs. compromiso de energía por contrato.",
            "headers": ["Contrato", "Generación (MWh)", "Compromiso (MWh)", "Cumplimiento (%)"],
            "rows": [
                [c.contrato, _fmt(c.gen_mwh, 2), _fmt(c.compromiso_mwh, 2),
                 _fmt(c.cumplimiento_pct, 1)]
                for c in agg.compliance
            ],
        })

    pdisp = periodo_display(agg.period_start, agg.period_end)
    # Avisos al analista. Si falta línea base P90 fiable, el índice de desempeño
    # sale en "—": hay que decirlo explícitamente, porque con datos reales
    # completos (gap=0) el informe se vería "completo" pese al KPI central vacío.
    avisos = []
    if gap > 0:
        avisos.append(f"Faltan {gap:.1f}% de los días de generación; "
                      "los indicadores pueden no ser representativos.")
    if agg.expected_kwh is None:
        avisos.append("Sin línea base P90 para el período; el índice de "
                      "desempeño no se puede calcular.")
    html = render_report(report_type, {
        "titulo": agg.proyecto_nombre,
        "periodo_display": pdisp,
        "kpis": kpis,
        "secciones": secciones,
        "alerta": " ".join(avisos) if avisos else None,
    })

    labels = [d.fecha for d in agg.daily]
    datasets = [{"label": "Real (kWh)", "data": [d.kwh_real for d in agg.daily]}]
    if any(d.kwh_p90 is not None for d in agg.daily):
        datasets.append({"label": "P90 (kWh)", "data": [d.kwh_p90 for d in agg.daily]})
    charts = {"generacion_diaria": generate_chart_data(labels, datasets)}

    return {
        "html_content": html,
        "charts_data": charts,
        "kpis": kpis,
        "gap_pct": gap,
        "periodo_display": pdisp,
    }


def build_portfolio_report(agg: PortfolioAggregate,
                           max_gap_pct: float = MAX_DATA_GAP_PCT) -> dict:
    """Construye el informe consolidado de un portafolio. Valida la completitud
    *agregada* (suma de días con dato / días esperados de todos los miembros)."""
    total_with = sum(m.days_with_data for m in agg.members)
    total_expected = sum(m.days_expected for m in agg.members)
    gap = validate_completeness(total_with, total_expected, max_gap_pct)

    total_kwh = sum(m.total_kwh or 0 for m in agg.members)
    total_expected_kwh = sum(m.expected_kwh or 0 for m in agg.members)
    total_kwp = sum(m.kwp or 0 for m in agg.members)
    hours = days_in_period(agg.period_start, agg.period_end) * 24
    fc = capacity_factor_pct(total_kwh or None, total_kwp or None, hours)
    pi = performance_index_pct(total_kwh or None, total_expected_kwh or None)

    kpis = [
        {"label": "Proyectos", "value": str(len(agg.members)), "unit": ""},
        {"label": "Generación total", "value": _fmt(total_kwh), "unit": "kWh"},
        {"label": "Esperado (P90)", "value": _fmt(total_expected_kwh or None), "unit": "kWh"},
        {"label": "Índice desempeño", "value": _fmt(pi, 1), "unit": "%"},
        {"label": "Factor de capacidad", "value": _fmt(fc, 2), "unit": "%"},
    ]
    seccion = {
        "titulo": "Detalle por proyecto",
        "descripcion": "Generación real vs. esperada (P90) por proyecto del portafolio.",
        "headers": ["Proyecto", "Generación (kWh)", "Esperado (kWh)", "Desempeño (%)"],
        "rows": [
            [m.nombre, _fmt(m.total_kwh), _fmt(m.expected_kwh),
             _fmt(performance_index_pct(m.total_kwh, m.expected_kwh), 1)]
            for m in agg.members
        ],
    }
    pdisp = periodo_display(agg.period_start, agg.period_end)
    html = render_report("port", {
        "titulo": agg.nombre,
        "periodo_display": pdisp,
        "kpis": kpis,
        "secciones": [seccion],
        "alerta": (f"Faltan {gap:.1f}% de los días de generación del portafolio.")
                  if gap > 0 else None,
    })

    labels = [m.nombre for m in agg.members]
    charts = {"generacion_por_proyecto": generate_chart_data(labels, [
        {"label": "Real (kWh)", "data": [m.total_kwh or 0 for m in agg.members]},
        {"label": "P90 (kWh)", "data": [m.expected_kwh or 0 for m in agg.members]},
    ])}

    return {
        "html_content": html,
        "charts_data": charts,
        "kpis": kpis,
        "gap_pct": gap,
        "periodo_display": pdisp,
    }


# ── Servicio (consultas a BD + delegación en builders) ───────────────────────

class ReportGenerator:
    """Genera borradores de informes a partir de la BD operativa."""

    def __init__(self, db: Session):
        self.db = db

    # -- consultas ------------------------------------------------------------

    def _query_proyecto(self, sub_project: str):
        return self.db.execute(
            text("""
                SELECT id, nombre_comercial, sub_project, potencia_instalada_kwp,
                       p90_mensual_kwh
                FROM proyectos
                WHERE (sub_project = :sp OR nombre_comercial = :sp)
                  AND deleted_at IS NULL
                LIMIT 1
            """),
            {"sp": sub_project},
        ).fetchone()

    def _query_generacion(self, proyecto_id: int, start: date, end: date):
        rows = self.db.execute(
            text("""
                SELECT fecha, kwh_real, kwh_p90, kwh_autoconsumo
                FROM generacion_diaria
                WHERE proyecto_id = :pid
                  AND fecha BETWEEN :start AND :end
                ORDER BY fecha
            """),
            {"pid": proyecto_id, "start": start, "end": end},
        ).fetchall()
        return rows

    def _query_cumplimiento(self, proyecto_id: int, start: date, end: date):
        """Filas de cumplimiento mensual del proyecto en el rango (por anio/mes)."""
        return self.db.execute(
            text("""
                SELECT cm.gen_total_mwh, cm.compromiso_mwh,
                       COALESCE(pc.nombre_interno, pc.comprador_nombre,
                                'Contrato ' || cm.contrato_ppa_id::text) AS contrato
                FROM cumplimiento_mensual cm
                LEFT JOIN ppa_contratos pc ON pc.id = cm.contrato_ppa_id
                WHERE cm.proyecto_id = :pid
                  AND (cm.anio * 100 + cm.mes) BETWEEN :ym_start AND :ym_end
                ORDER BY cm.anio, cm.mes
            """),
            {
                "pid": proyecto_id,
                "ym_start": start.year * 100 + start.month,
                "ym_end": end.year * 100 + end.month,
            },
        ).fetchall()

    # -- agregación -----------------------------------------------------------

    def _build_project_aggregate(self, proyecto, start: date, end: date,
                                 with_compliance: bool) -> ProjectAggregate:
        gen_rows = self._query_generacion(proyecto.id, start, end)
        daily = [
            DailyPoint(
                fecha=r.fecha.isoformat() if hasattr(r.fecha, "isoformat") else str(r.fecha),
                kwh_real=float(r.kwh_real) if r.kwh_real is not None else None,
                kwh_p90=float(r.kwh_p90) if r.kwh_p90 is not None else None,
            )
            for r in gen_rows
        ]
        total_kwh = sum(d.kwh_real for d in daily if d.kwh_real is not None) or None
        days_with_data = sum(1 for d in daily if d.kwh_real is not None)
        # Esperado del período (P90). El P90 diario sólo es fiable cuando cubre al
        # menos los mismos días que tienen generación real: si está más escaso
        # (filas con kwh_real pero kwh_p90 NULL — frecuente en import_generacion_
        # sheets/bulk upsert) su suma SUBESTIMA el esperado del mes e infla el
        # índice de desempeño. En ese caso preferimos el P90 mensual (cubre el mes
        # completo); si tampoco hay, dejamos el esperado en None (KPI "—") en vez
        # de publicar un índice de desempeño inflado.
        days_with_p90 = sum(1 for d in daily if d.kwh_p90 is not None)
        monthly_p90 = self._expected_from_p90_mensual(proyecto, start, end)
        if days_with_p90 and days_with_p90 >= days_with_data:
            expected = sum(d.kwh_p90 for d in daily if d.kwh_p90 is not None) or monthly_p90
        else:
            expected = monthly_p90
        autoconsumo = sum(
            float(r.kwh_autoconsumo) for r in gen_rows if r.kwh_autoconsumo is not None
        ) or None

        agg = ProjectAggregate(
            proyecto_nombre=proyecto.nombre_comercial,
            sub_project=proyecto.sub_project or proyecto.nombre_comercial,
            kwp=float(proyecto.potencia_instalada_kwp) if proyecto.potencia_instalada_kwp else None,
            period_start=start,
            period_end=end,
            total_kwh=total_kwh,
            expected_kwh=expected,
            autoconsumo_kwh=autoconsumo,
            days_with_data=days_with_data,
            daily=daily,
        )
        if with_compliance:
            agg.compliance = [
                ComplianceRow(
                    contrato=r.contrato,
                    gen_mwh=float(r.gen_total_mwh) if r.gen_total_mwh is not None else None,
                    compromiso_mwh=float(r.compromiso_mwh) if r.compromiso_mwh is not None else None,
                )
                for r in self._query_cumplimiento(proyecto.id, start, end)
            ]
        return agg

    @staticmethod
    def _expected_from_p90_mensual(proyecto, start: date, end: date) -> float | None:
        """Estimación de generación esperada a partir de ``p90_mensual_kwh``
        (array de 12 valores, índice 0 = enero) cuando no hay P90 diario."""
        arr = getattr(proyecto, "p90_mensual_kwh", None)
        if not arr or not isinstance(arr, (list, tuple)):
            return None
        total = 0.0
        found = False
        # Suma los meses cubiertos por el período (informes mensuales: 1 mes).
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            idx = m - 1
            if 0 <= idx < len(arr) and arr[idx] is not None:
                try:
                    total += float(arr[idx])
                    found = True
                except (TypeError, ValueError):
                    pass
            m += 1
            if m > 12:
                m = 1
                y += 1
        return total if found else None

    # -- API pública del servicio --------------------------------------------

    def _generate_for_project(self, report_type: str, sub_project: str,
                              start: date, end: date) -> dict:
        proyecto = self._query_proyecto(sub_project)
        if not proyecto:
            raise ValueError(f"Proyecto no encontrado: '{sub_project}'")
        agg = self._build_project_aggregate(
            proyecto, start, end, with_compliance=(report_type == "fmo"),
        )
        result = build_project_report(report_type, agg)
        result.update({
            "tipo": report_type,
            "sub_project": agg.sub_project,
            "proyecto_nombre": agg.proyecto_nombre,
            "periodo_desde": start.isoformat(),
            "periodo_hasta": end.isoformat(),
        })
        return result

    def generate_op_report(self, sub_project: str, start: date, end: date) -> dict:
        return self._generate_for_project("op", sub_project, start, end)

    def generate_fmo_report(self, sub_project: str, start: date, end: date) -> dict:
        return self._generate_for_project("fmo", sub_project, start, end)

    def generate_port_report(self, portafolio: str, start: date, end: date) -> dict:
        """``portafolio`` puede ser el nombre o el id (como string) del portafolio."""
        pf = self.db.execute(
            text("""
                SELECT id, nombre FROM portafolios
                WHERE nombre = :p OR CAST(id AS TEXT) = :p
                LIMIT 1
            """),
            {"p": str(portafolio)},
        ).fetchone()
        if not pf:
            raise ValueError(f"Portafolio no encontrado: '{portafolio}'")

        proyectos = self.db.execute(
            text("""
                SELECT id, nombre_comercial, sub_project, potencia_instalada_kwp,
                       p90_mensual_kwh
                FROM proyectos
                WHERE portafolio_id = :pid AND deleted_at IS NULL
                ORDER BY nombre_comercial
            """),
            {"pid": pf.id},
        ).fetchall()

        members: list[PortfolioMember] = []
        for p in proyectos:
            sub = self._build_project_aggregate(p, start, end, with_compliance=False)
            members.append(PortfolioMember(
                nombre=sub.proyecto_nombre,
                total_kwh=sub.total_kwh,
                expected_kwh=sub.expected_kwh,
                kwp=sub.kwp,
                days_with_data=sub.days_with_data,
                days_expected=sub.days_expected,
            ))

        agg = PortfolioAggregate(
            nombre=pf.nombre, sub_project=pf.nombre,
            period_start=start, period_end=end, members=members,
        )
        result = build_portfolio_report(agg)
        result.update({
            "tipo": "port",
            "sub_project": pf.nombre,
            "proyecto_nombre": pf.nombre,
            "periodo_desde": start.isoformat(),
            "periodo_hasta": end.isoformat(),
            "miembros": [
                {"sub_project": m.nombre, "nombre": m.nombre, "orden": i}
                for i, m in enumerate(members)
            ],
        })
        return result
