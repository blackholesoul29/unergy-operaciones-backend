"""Tests del motor de indexación PPA (función pura `calcular_tarifas`).

Math verificada con historial de índices mockeado — sin DB.
"""
import pytest

from app.schemas.ppa_indexation import IndexType, Frequency, normalize_index_type
from app.services.ppa_indexation import calcular_tarifas


# ── IPC (historial real estilo om_ipc_tasas: {año -> tasa dic}) ────────────────

def test_ipc_compone_factor_acumulado_anual():
    res = calcular_tarifas(
        index_type=IndexType.IPC,
        base_rate=100.0,
        base_period="2024-01",
        base_index_value=None,
        frequency=Frequency.anual,
        periodos=[(2024, 6), (2025, 6), (2026, 6)],
        index_history={2024: 0.052, 2025: 0.051},
        currency="COP",
    )
    finals = {(r.año, r.mes): r.final_rate for r in res}
    assert finals[(2024, 6)] == pytest.approx(100.0)        # año base, factor 1
    assert finals[(2025, 6)] == pytest.approx(105.2)        # ×1.052
    assert finals[(2026, 6)] == pytest.approx(110.5652)     # ×1.052×1.051
    assert all(r.currency == "COP" for r in res)


def test_ipc_mes_dentro_del_anio_comparte_factor():
    res = calcular_tarifas(
        index_type=IndexType.IPC,
        base_rate=200.0,
        base_period="2024-01",
        base_index_value=None,
        frequency=Frequency.anual,
        periodos=[(2025, 1), (2025, 12)],
        index_history={2024: 0.10},
    )
    assert res[0].final_rate == pytest.approx(220.0)
    assert res[1].final_rate == pytest.approx(220.0)


# ── FIJO (sin indexación) ──────────────────────────────────────────────────────

def test_fijo_no_indexa():
    res = calcular_tarifas(
        index_type=IndexType.FIJO,
        base_rate=150.0,
        base_period="2024-01",
        base_index_value=None,
        frequency=Frequency.anual,
        periodos=[(2024, 1), (2030, 12)],
        index_history={},
    )
    assert all(r.final_rate == pytest.approx(150.0) for r in res)
    assert all(r.applied_index == pytest.approx(1.0) for r in res)


# ── Series tipo USD (ratio valor/valor_base) ───────────────────────────────────

def test_usd_aplica_ratio_de_serie():
    res = calcular_tarifas(
        index_type=IndexType.USD,
        base_rate=10.0,
        base_period="2025-01",
        base_index_value=4000.0,
        frequency=Frequency.mensual,
        periodos=[(2025, 1), (2025, 2)],
        index_history={"2025-01": 4000.0, "2025-02": 4200.0},
        currency="USD",
    )
    assert res[0].final_rate == pytest.approx(10.0)
    assert res[1].final_rate == pytest.approx(10.5)
    assert res[1].applied_index == pytest.approx(4200.0)
    assert all(r.currency == "USD" for r in res)


def test_serie_sin_dato_es_placeholder_con_nota():
    res = calcular_tarifas(
        index_type=IndexType.DIPREM,
        base_rate=50.0,
        base_period="2025-01",
        base_index_value=None,
        frequency=Frequency.mensual,
        periodos=[(2025, 3)],
        index_history={},
    )
    assert res[0].final_rate == pytest.approx(50.0)   # sin serie → factor 1.0
    assert res[0].nota is not None


# ── Normalización de índices ───────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("IPC", IndexType.IPC),
    ("ipc anual", IndexType.IPC),
    ("USD", IndexType.USD),
    ("Dólar", IndexType.USD),
    (None, IndexType.FIJO),
    ("", IndexType.FIJO),
    ("Ninguno", IndexType.FIJO),
])
def test_normalize_index_type(raw, expected):
    assert normalize_index_type(raw) == expected


def test_normalize_index_type_desconocido_lanza():
    with pytest.raises(ValueError):
        normalize_index_type("XYZ-RARO")


# ── Persistencia: upsert idempotente (SQLite en memoria) ───────────────────────

@pytest.fixture()
def db_session():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    eng = create_engine("sqlite://")
    # `id` como INTEGER autoincrement (SQLite no autoincrementa BIGINT).
    with eng.begin() as c:
        c.execute(text(
            'CREATE TABLE ppa_tarifas ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, '
            'contrato_id INTEGER NOT NULL, "año" INTEGER NOT NULL, '
            'mes INTEGER NOT NULL, tarifa NUMERIC, '
            'UNIQUE(contrato_id, "año", mes))'
        ))
    db = sessionmaker(bind=eng)()
    yield db
    db.close()


def test_create_bulk_from_contract_inserta_y_es_idempotente(db_session):
    from app.models.contratos import PPATarifa
    from app.schemas.ppa_indexation import TariffCalculationResult as T

    rows = [
        T(año=2025, mes=1, base_rate=100, final_rate=105),
        T(año=2025, mes=2, base_rate=100, final_rate=110),
    ]
    stats1 = PPATarifa.create_bulk_from_contract(db_session, 7, rows)
    db_session.commit()
    assert stats1 == {"created": 2, "updated": 0}
    assert db_session.query(PPATarifa).count() == 2

    # Re-correr con un valor cambiado → no duplica, actualiza.
    rows2 = [
        T(año=2025, mes=1, base_rate=100, final_rate=999),
        T(año=2025, mes=2, base_rate=100, final_rate=110),
    ]
    stats2 = PPATarifa.create_bulk_from_contract(db_session, 7, rows2)
    db_session.commit()
    assert stats2 == {"created": 0, "updated": 2}
    assert db_session.query(PPATarifa).count() == 2
    actualizada = db_session.query(PPATarifa).filter_by(año=2025, mes=1).first()
    assert float(actualizada.tarifa) == pytest.approx(999.0)
