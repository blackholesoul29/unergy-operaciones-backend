"""
Tests del servicio de cumplimiento PPA (comprometido vs. generado).

Se centran en la lógica de cálculo pura (delta, %, agregación de flota) y en la
orquestación por proyecto/flota, sustituyendo el acceso a base de datos por
dobles ligeros — igual que el resto de la suite, que corre sin DB real.
"""
from types import SimpleNamespace

from app.services.ppa_compliance import PPAComplianceService


# ── compute_compliance: cálculo de delta y porcentaje ─────────────────────────

def test_compute_compliance_deficit():
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=100.0, actual_mwh=90.0)
    assert delta == -10.0
    assert pct == 90.0


def test_compute_compliance_excedente():
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=100.0, actual_mwh=125.0)
    assert delta == 25.0
    assert pct == 125.0


def test_compute_compliance_generacion_cero():
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=80.0, actual_mwh=0.0)
    assert delta == -80.0
    assert pct == 0.0


def test_compute_compliance_actual_none_se_trata_como_cero():
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=50.0, actual_mwh=None)
    assert delta == -50.0
    assert pct == 0.0


def test_compute_compliance_sin_ppa():
    # Sin compromiso definido → delta y % en None (no se inventa cumplimiento).
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=None, actual_mwh=120.0)
    assert delta is None
    assert pct is None


def test_compute_compliance_target_cero_no_divide_por_cero():
    delta, pct = PPAComplianceService.compute_compliance(target_mwh=0.0, actual_mwh=10.0)
    assert delta == 10.0
    assert pct is None


# ── aggregate_fleet: agregación de varios proyectos ───────────────────────────

def _row(pid, target, actual, has_ppa):
    delta, pct = PPAComplianceService.compute_compliance(target, actual)
    return {
        "project_id": pid, "target_mwh": target, "actual_mwh": actual,
        "delta_mwh": delta, "compliance_pct": pct, "has_ppa": has_ppa,
    }


def test_aggregate_fleet_suma_solo_proyectos_con_ppa():
    rows = [
        _row(1, 100.0, 90.0, True),
        _row(2, 50.0, 60.0, True),
        _row(3, None, 30.0, False),   # sin PPA → no suma a totales
    ]
    summary = PPAComplianceService.aggregate_fleet(rows)
    assert summary["total_target_mwh"] == 150.0
    assert summary["total_actual_mwh"] == 150.0
    assert summary["total_delta_mwh"] == 0.0
    assert summary["fleet_compliance_pct"] == 100.0
    assert summary["n_proyectos"] == 3
    assert summary["n_con_ppa"] == 2


def test_aggregate_fleet_sin_compromisos():
    rows = [_row(1, None, 10.0, False), _row(2, None, 20.0, False)]
    summary = PPAComplianceService.aggregate_fleet(rows)
    assert summary["total_target_mwh"] == 0.0
    assert summary["fleet_compliance_pct"] is None
    assert summary["n_con_ppa"] == 0


# ── _row: construcción del registro por proyecto ──────────────────────────────

def test_row_marca_has_ppa_segun_target():
    svc = PPAComplianceService(db=None)
    con = svc._row(7, target=100.0, actual=80.0, nombre="MGS 0001")
    assert con == {
        "project_id": 7, "target_mwh": 100.0, "actual_mwh": 80.0,
        "delta_mwh": -20.0, "compliance_pct": 80.0, "has_ppa": True,
        "nombre": "MGS 0001",
    }
    sin = svc._row(8, target=None, actual=5.0)
    assert sin["has_ppa"] is False
    assert sin["compliance_pct"] is None
    assert "nombre" not in sin


# ── Orquestación por proyecto ─────────────────────────────────────────────────

class _FakeProjectQuery:
    def __init__(self, proyecto):
        self._proyecto = proyecto

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._proyecto

    def all(self):
        return [self._proyecto] if self._proyecto else []


class _FakeDB:
    """DB mínima: devuelve un proyecto fijo para query(Proyecto)."""
    def __init__(self, proyectos):
        self._proyectos = proyectos

    def query(self, model):
        return _FakeProjectQuery(self._proyectos[0] if self._proyectos else None)


def _service_con_datos(proyectos, targets, generacion):
    svc = PPAComplianceService(db=_FakeDB(proyectos))
    svc._build_targets_map = lambda year, month: targets
    svc._get_all_generation = lambda year, month: generacion
    return svc


def test_calculate_project_compliance_con_ppa_y_generacion():
    proyecto = SimpleNamespace(id=1, nombre_comercial="MGS 0001 Test")
    svc = _service_con_datos([proyecto], targets={1: 100.0}, generacion={1: 90.0})
    out = svc.calculate_project_compliance(1, 2026, 6)
    assert out["project_id"] == 1
    assert out["nombre"] == "MGS 0001 Test"
    assert out["target_mwh"] == 100.0
    assert out["actual_mwh"] == 90.0
    assert out["delta_mwh"] == -10.0
    assert out["compliance_pct"] == 90.0
    assert out["has_ppa"] is True
    assert out["year"] == 2026 and out["month"] == 6


def test_calculate_project_compliance_generacion_cero():
    proyecto = SimpleNamespace(id=1, nombre_comercial="MGS 0001 Test")
    svc = _service_con_datos([proyecto], targets={1: 100.0}, generacion={})
    out = svc.calculate_project_compliance(1, 2026, 6)
    assert out["actual_mwh"] == 0.0
    assert out["delta_mwh"] == -100.0
    assert out["compliance_pct"] == 0.0


def test_calculate_project_compliance_sin_ppa():
    proyecto = SimpleNamespace(id=2, nombre_comercial="Planta Sin PPA")
    svc = _service_con_datos([proyecto], targets={}, generacion={2: 40.0})
    out = svc.calculate_project_compliance(2, 2026, 6)
    assert out["has_ppa"] is False
    assert out["target_mwh"] is None
    assert out["delta_mwh"] is None
    assert out["compliance_pct"] is None
    assert out["actual_mwh"] == 40.0   # generación real igual se reporta


# ── Orquestación de flota ─────────────────────────────────────────────────────

def test_calculate_fleet_compliance_agrega_multiples_proyectos():
    proyectos = [
        SimpleNamespace(id=1, nombre_comercial="A"),
        SimpleNamespace(id=2, nombre_comercial="B"),
        SimpleNamespace(id=3, nombre_comercial="C"),  # sin PPA
    ]

    class _MultiQuery(_FakeProjectQuery):
        def all(self_inner):
            return proyectos

    class _MultiDB:
        def query(self_inner, model):
            return _MultiQuery(None)

    svc = PPAComplianceService(db=_MultiDB())
    svc._build_targets_map = lambda y, m: {1: 100.0, 2: 50.0}
    svc._get_all_generation = lambda y, m: {1: 90.0, 2: 55.0, 3: 20.0}

    out = svc.calculate_fleet_compliance(2026, 6)
    assert out["year"] == 2026 and out["month"] == 6
    assert out["n_proyectos"] == 3
    assert out["n_con_ppa"] == 2
    assert out["total_target_mwh"] == 150.0
    assert out["total_actual_mwh"] == 145.0
    assert out["total_delta_mwh"] == -5.0
    # 145 / 150 * 100 = 96.67
    assert out["fleet_compliance_pct"] == 96.67
    assert len(out["proyectos"]) == 3
    # El proyecto sin PPA aparece en el desglose pero no suma a los totales.
    c = next(r for r in out["proyectos"] if r["project_id"] == 3)
    assert c["has_ppa"] is False and c["actual_mwh"] == 20.0
