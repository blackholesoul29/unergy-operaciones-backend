"""Tests de la lógica pura de generación de informes (sin BD)."""
from datetime import date

import pytest

from app.services.report_generator import (
    DataGapError,
    ComplianceRow,
    DailyPoint,
    PortfolioAggregate,
    PortfolioMember,
    ProjectAggregate,
    build_portfolio_report,
    build_project_report,
    capacity_factor_pct,
    compliance_pct,
    completeness_pct,
    data_gap_pct,
    days_in_period,
    performance_index_pct,
    periodo_display,
    validate_completeness,
)
from app.utils.report_templates import generate_chart_data, render_report


# ── Helpers puros ────────────────────────────────────────────────────────────

def test_days_in_period_inclusive():
    assert days_in_period(date(2026, 5, 1), date(2026, 5, 31)) == 31
    assert days_in_period(date(2026, 5, 1), date(2026, 5, 1)) == 1
    assert days_in_period(date(2026, 5, 2), date(2026, 5, 1)) == 0


def test_capacity_factor():
    # 100 kWp durante 24h = 2400 kWh teóricos; 1200 reales → 50%
    assert capacity_factor_pct(1200, 100, 24) == 50.0
    assert capacity_factor_pct(0, 100, 24) is None       # sin generación
    assert capacity_factor_pct(1200, 0, 24) is None       # sin potencia
    assert capacity_factor_pct(1200, 100, 0) is None      # sin horas


def test_performance_index():
    assert performance_index_pct(900, 1000) == 90.0
    assert performance_index_pct(None, 1000) is None
    assert performance_index_pct(900, 0) is None
    assert performance_index_pct(900, None) is None


def test_compliance_pct():
    assert compliance_pct(95, 100) == 95.0
    assert compliance_pct(None, 100) is None
    assert compliance_pct(95, 0) is None


def test_completeness_and_gap():
    assert completeness_pct(30, 31) == pytest.approx(96.7741, abs=1e-3)
    assert completeness_pct(31, 31) == 100.0
    assert completeness_pct(40, 31) == 100.0       # cap a 100
    assert completeness_pct(0, 0) == 0.0
    assert data_gap_pct(30, 31) == pytest.approx(3.2258, abs=1e-3)


def test_validate_completeness_ok_and_raises():
    # 30/31 días → ~3.2% gap, dentro del 5% → ok
    assert validate_completeness(30, 31) == pytest.approx(3.2258, abs=1e-3)
    # 15/31 → ~52% gap → DataGapError
    with pytest.raises(DataGapError) as exc:
        validate_completeness(15, 31)
    assert exc.value.code == "DATA_GAP"
    assert exc.value.days_with_data == 15
    assert exc.value.gap_pct > 5.0


def test_periodo_display():
    assert periodo_display(date(2026, 5, 1), date(2026, 5, 31)) == "Mayo 2026"
    assert periodo_display(date(2026, 2, 1), date(2026, 2, 28)) == "Febrero 2026"
    # rango parcial → no es etiqueta de mes
    assert "—" in periodo_display(date(2026, 5, 1), date(2026, 5, 15))


# ── generate_chart_data ──────────────────────────────────────────────────────

def test_generate_chart_data_shape():
    out = generate_chart_data(["a", "b"], [{"label": "x", "data": [1, 2]}])
    assert out == {"labels": ["a", "b"],
                   "datasets": [{"label": "x", "data": [1, 2]}]}


def test_generate_chart_data_length_mismatch_raises():
    with pytest.raises(ValueError):
        generate_chart_data(["a", "b", "c"], [{"label": "x", "data": [1, 2]}])


def test_render_report_smoke():
    html = render_report("op", {
        "titulo": "Proyecto X", "periodo_display": "Mayo 2026",
        "kpis": [{"label": "Generación", "value": "1,000", "unit": "kWh"}],
        "secciones": [],
    })
    assert "Proyecto X" in html
    assert "rpt-page" in html
    assert "Mayo 2026" in html


# ── build_project_report ─────────────────────────────────────────────────────

def _good_daily(n_days: int, n_with_data: int, kwh: float = 100.0) -> list[DailyPoint]:
    pts = []
    for i in range(n_days):
        has = i < n_with_data
        pts.append(DailyPoint(
            fecha=f"2026-05-{i + 1:02d}",
            kwh_real=kwh if has else None,
            kwh_p90=110.0,
        ))
    return pts


def test_build_op_report_aggregates_single_project():
    agg = ProjectAggregate(
        proyecto_nombre="Planta Solar Uno",
        sub_project="PSU",
        kwp=100.0,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        total_kwh=3100.0,
        expected_kwh=3410.0,
        days_with_data=31,
        daily=_good_daily(31, 31),
    )
    out = build_project_report("op", agg)
    assert out["periodo_display"] == "Mayo 2026"
    assert out["gap_pct"] == 0.0
    assert "Planta Solar Uno" in out["html_content"]
    # charts: serie real + serie p90
    chart = out["charts_data"]["generacion_diaria"]
    assert len(chart["labels"]) == 31
    assert len(chart["datasets"]) == 2
    # KPI desempeño ≈ 3100/3410 = 90.9%
    labels = {k["label"]: k["value"] for k in out["kpis"]}
    assert "Índice desempeño" in labels
    assert "Factor de capacidad" in labels


def test_build_fmo_report_includes_compliance_section():
    agg = ProjectAggregate(
        proyecto_nombre="Planta FMO",
        sub_project="PFMO",
        kwp=50.0,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        total_kwh=1550.0,
        expected_kwh=1600.0,
        days_with_data=31,
        daily=_good_daily(31, 31, kwh=50.0),
        compliance=[ComplianceRow(contrato="Terpel", gen_mwh=95.0, compromiso_mwh=100.0)],
    )
    out = build_project_report("fmo", agg)
    assert "Cumplimiento PPA" in out["html_content"]
    assert "Terpel" in out["html_content"]
    labels = {k["label"] for k in out["kpis"]}
    assert "Cumplimiento PPA" in labels


def test_build_report_data_gap_raises():
    # 15/31 días con datos → >5% gap → DataGapError (no se genera)
    agg = ProjectAggregate(
        proyecto_nombre="Planta Incompleta",
        sub_project="PI",
        kwp=100.0,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        total_kwh=1500.0,
        expected_kwh=3410.0,
        days_with_data=15,
        daily=_good_daily(31, 15),
    )
    with pytest.raises(DataGapError):
        build_project_report("op", agg)


# ── build_portfolio_report ───────────────────────────────────────────────────

def test_build_portfolio_report():
    members = [
        PortfolioMember("A", total_kwh=3100.0, expected_kwh=3000.0, kwp=100.0,
                        days_with_data=31, days_expected=31),
        PortfolioMember("B", total_kwh=2000.0, expected_kwh=2200.0, kwp=80.0,
                        days_with_data=30, days_expected=31),
    ]
    agg = PortfolioAggregate(nombre="Fondo Norte", sub_project="Fondo Norte",
                             period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
                             members=members)
    out = build_portfolio_report(agg)
    assert "Fondo Norte" in out["html_content"]
    assert "A" in out["html_content"] and "B" in out["html_content"]
    chart = out["charts_data"]["generacion_por_proyecto"]
    assert chart["labels"] == ["A", "B"]
    labels = {k["label"]: k["value"] for k in out["kpis"]}
    assert labels["Proyectos"] == "2"


def test_build_portfolio_report_data_gap_raises():
    members = [
        PortfolioMember("A", total_kwh=1500.0, expected_kwh=3000.0, kwp=100.0,
                        days_with_data=15, days_expected=31),
    ]
    agg = PortfolioAggregate(nombre="Fondo Pobre", sub_project="Fondo Pobre",
                             period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
                             members=members)
    with pytest.raises(DataGapError):
        build_portfolio_report(agg)


# ── ReportGenerator con sesión de BD simulada ────────────────────────────────

from types import SimpleNamespace

from app.services.report_generator import ReportGenerator


class _FakeResult:
    def __init__(self, one=None, many=None):
        self._one = one
        self._many = many or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _FakeSession:
    """Sesión mínima que responde a las consultas del ReportGenerator según el
    texto del SQL. Permite probar la agregación end-to-end sin BD real."""

    def __init__(self, proyecto, gen_rows, cumpl_rows=None):
        self.proyecto = proyecto
        self.gen_rows = gen_rows
        self.cumpl_rows = cumpl_rows or []

    def execute(self, query, params=None):
        sql = str(query)
        if "FROM proyectos" in sql:
            return _FakeResult(one=self.proyecto)
        if "FROM generacion_diaria" in sql:
            return _FakeResult(many=self.gen_rows)
        if "FROM cumplimiento_mensual" in sql:
            return _FakeResult(many=self.cumpl_rows)
        return _FakeResult()


def _proyecto(**kw):
    base = dict(id=1, nombre_comercial="Planta Mock", sub_project="PMOCK",
                potencia_instalada_kwp=100.0, p90_mensual_kwh=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _gen_rows(n_days, n_with_data, kwh=100.0, p90=110.0):
    rows = []
    for i in range(n_days):
        has = i < n_with_data
        rows.append(SimpleNamespace(
            fecha=date(2026, 5, i + 1),
            kwh_real=kwh if has else None,
            kwh_p90=p90,
            kwh_autoconsumo=None,
        ))
    return rows


def test_generator_op_aggregates_mock_data():
    db = _FakeSession(_proyecto(), _gen_rows(31, 31))
    out = ReportGenerator(db).generate_op_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))
    assert out["tipo"] == "op"
    assert out["sub_project"] == "PMOCK"
    assert out["proyecto_nombre"] == "Planta Mock"
    assert out["periodo_desde"] == "2026-05-01"
    assert "Planta Mock" in out["html_content"]
    assert out["charts_data"]["generacion_diaria"]["labels"]


def test_generator_fmo_includes_compliance():
    cumpl = [SimpleNamespace(gen_total_mwh=95.0, compromiso_mwh=100.0, contrato="Terpel")]
    db = _FakeSession(_proyecto(), _gen_rows(31, 31, kwh=50.0), cumpl_rows=cumpl)
    out = ReportGenerator(db).generate_fmo_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))
    assert out["tipo"] == "fmo"
    assert "Terpel" in out["html_content"]


def test_generator_data_gap_raises():
    # 15/31 días con datos → >5% gap
    db = _FakeSession(_proyecto(), _gen_rows(31, 15))
    with pytest.raises(DataGapError):
        ReportGenerator(db).generate_op_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))


def test_generator_unknown_project_raises_valueerror():
    db = _FakeSession(None, [])
    with pytest.raises(ValueError):
        ReportGenerator(db).generate_op_report("NOPE", date(2026, 5, 1), date(2026, 5, 31))


def test_generator_uses_p90_mensual_fallback():
    # Sin P90 diario (None) pero con p90_mensual_kwh → usa el de mayo (índice 4).
    p90_arr = [0] * 12
    p90_arr[4] = 3400.0
    rows = _gen_rows(31, 31, kwh=100.0, p90=None)
    db = _FakeSession(_proyecto(p90_mensual_kwh=p90_arr), rows)
    out = ReportGenerator(db).generate_op_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))
    # KPI "Esperado (P90)" debe reflejar 3.400
    esperado = {k["label"]: k["value"] for k in out["kpis"]}["Esperado (P90)"]
    assert "3,400" in esperado


def _gen_rows_partial_p90(n_days, kwh, p90, n_with_p90):
    """31 días con kwh_real, pero P90 diario sólo en los primeros ``n_with_p90``."""
    rows = []
    for i in range(n_days):
        rows.append(SimpleNamespace(
            fecha=date(2026, 5, i + 1),
            kwh_real=kwh,
            kwh_p90=p90 if i < n_with_p90 else None,
            kwh_autoconsumo=None,
        ))
    return rows


def test_partial_daily_p90_does_not_inflate_performance_index():
    # Datos reales completos (31 días) pero P90 diario sólo en 10 días.
    # Sumar el P90 diario PARCIAL (10·110=1.100) subestima el esperado del mes
    # e infla el índice de desempeño (3.100/1.100 ≈ 282%). Con P90 mensual
    # disponible (3.400) el esperado debe ser el del MES completo → PI ≈ 91%.
    p90_arr = [0] * 12
    p90_arr[4] = 3400.0
    rows = _gen_rows_partial_p90(31, kwh=100.0, p90=110.0, n_with_p90=10)
    db = _FakeSession(_proyecto(p90_mensual_kwh=p90_arr), rows)
    out = ReportGenerator(db).generate_op_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))
    kpis = {k["label"]: k["value"] for k in out["kpis"]}
    assert "3,400" in kpis["Esperado (P90)"], kpis["Esperado (P90)"]
    # 3.100 / 3.400 ≈ 91,2% (no el 281,8% que daría el P90 parcial)
    pi = float(kpis["Índice desempeño"].replace(",", ""))
    assert 85.0 <= pi <= 95.0, pi


def test_partial_daily_p90_without_monthly_yields_no_expected():
    # P90 diario parcial y sin P90 mensual → no hay esperado fiable del período;
    # el KPI debe ser "—" en lugar de un índice de desempeño inflado.
    rows = _gen_rows_partial_p90(31, kwh=100.0, p90=110.0, n_with_p90=10)
    db = _FakeSession(_proyecto(p90_mensual_kwh=None), rows)
    out = ReportGenerator(db).generate_op_report("PMOCK", date(2026, 5, 1), date(2026, 5, 31))
    kpis = {k["label"]: k["value"] for k in out["kpis"]}
    assert kpis["Esperado (P90)"] == "—", kpis["Esperado (P90)"]
    assert kpis["Índice desempeño"] == "—", kpis["Índice desempeño"]
