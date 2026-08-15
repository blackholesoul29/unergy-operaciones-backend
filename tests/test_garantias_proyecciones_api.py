"""Persistencia + endpoint de proyecciones de garantía. Harness sqlite; se invocan las
funciones del router directamente (auth stubeada en conftest). Deps externas mockeadas."""
import types
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos)
from app.models.garantias_proyecciones import GarantiaSnapshot, GarantiaPagado
from app.services.garantias_proyecciones import filas_snapshot, pagado_por_periodo, set_pagado
from app.services import garantias_proyecciones as svc
from app.api.v1 import garantias_proyecciones as api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


USER = types.SimpleNamespace(id=1)


def test_guardar_y_leer_snapshot(db):
    fila = GarantiaSnapshot(
        fecha_corte=date(2026, 8, 14), clave="resto_mes_actual", anio=2026, mes=8,
        neto_mwh=26.0, precio_bolsa=900.0, valor_energia=23_400_000.0,
        valor_plantas_nuevas=0.0, costo_regulatorio=1_000_000.0,
        garantia_total=24_400_000.0, plantas_nuevas=0, kwh_planta_nueva=180.0,
        regulatorio_anio=2026, regulatorio_mes=7, regulatorio_fallback=False,
    )
    db.add(fila)
    db.commit()
    leido = db.query(GarantiaSnapshot).one()
    assert leido.clave == "resto_mes_actual"
    assert float(leido.garantia_total) == 24_400_000.0


def _resultado_demo():
    return {
        "fecha_corte": "2026-08-14", "precio_bolsa_cop_kwh": 900.0,
        "plantas_nuevas": 0, "kwh_planta_nueva": 180.0,
        "ventanas": [
            {"clave": "resto_mes_actual", "anio": 2026, "mes": 8, "neto_mwh": 26.0,
             "energia_neta_kwh": 26000.0, "valor_energia": 23_400_000.0,
             "valor_plantas_nuevas": 0.0, "costo_regulatorio": 1_000_000.0,
             "garantia_total": 24_400_000.0,
             "regulatorio_periodo": {"anio": 2026, "mes": 7, "fallback": False}},
            {"clave": "mes_siguiente", "anio": 2026, "mes": 9, "neto_mwh": 44.0,
             "energia_neta_kwh": 44000.0, "valor_energia": 39_600_000.0,
             "valor_plantas_nuevas": 0.0, "costo_regulatorio": 2_000_000.0,
             "garantia_total": 41_600_000.0,
             "regulatorio_periodo": {"anio": 2026, "mes": 8, "fallback": True}},
        ],
    }


def test_filas_snapshot_una_por_ventana(db):
    filas = filas_snapshot(_resultado_demo())
    assert len(filas) == 2
    f0 = filas[0]
    assert f0.clave == "resto_mes_actual"
    assert f0.fecha_corte == date(2026, 8, 14)
    assert float(f0.garantia_total) == 24_400_000.0
    assert f0.regulatorio_mes == 7 and f0.regulatorio_fallback is False
    assert filas[1].regulatorio_fallback is True


def test_construir_live_usa_deps_reales_mockeadas(db, monkeypatch):
    bal = {"balance": {"ungg": {
        "venta_bolsa": {"real": 0.0, "proyectado": 30.0, "total": 50.0, "n_plantas": 1},
        "compra_bolsa_directa": {"real": 0.0, "proyectado": 4.0, "total": 6.0, "n_plantas": 1},
    }}, "periodo": {}}
    monkeypatch.setattr(svc, "_balance_fn", lambda db_, a, m: bal)
    monkeypatch.setattr(svc, "_precio_fn", lambda: 900.0)
    monkeypatch.setattr(svc, "_regulatorio_fn",
                        lambda a, m: {"valor": 1_000_000.0, "anio": a, "mes": m, "fallback": False})

    res = svc.construir_proyecciones_live(db, hoy=date(2026, 8, 14))
    assert res["precio_bolsa_cop_kwh"] == 900.0
    assert res["ventanas"][0]["garantia_total"] == 26.0 * 1000 * 900.0 + 1_000_000.0


def test_guardar_y_historial(db):
    from app.services.garantias_proyecciones import guardar_snapshot, historial_snapshots
    r1 = _resultado_demo()
    guardar_snapshot(db, r1)
    hist = historial_snapshots(db)
    assert len(hist) == 2  # dos ventanas
    assert {h.clave for h in hist} == {"resto_mes_actual", "mes_siguiente"}


def test_endpoint_get_calcula_en_vivo(db, monkeypatch):
    monkeypatch.setattr(api, "construir_proyecciones_live",
                        lambda db_, plantas_nuevas=0, kwh_planta_nueva=180.0: {"ok": True,
                            "ventanas": [], "fecha_corte": "2026-08-14"})
    out = api.get_proyecciones(plantas_nuevas=0, kwh_planta_nueva=180.0, db=db, _=USER)
    assert out["ok"] is True


def test_endpoint_post_guarda_snapshot(db, monkeypatch):
    monkeypatch.setattr(api, "construir_proyecciones_live",
                        lambda db_, plantas_nuevas=0, kwh_planta_nueva=180.0: _resultado_demo())
    out = api.post_snapshot(plantas_nuevas=0, kwh_planta_nueva=180.0, db=db, _=USER)
    assert out["guardadas"] == 2
    # y quedan en el historial
    assert len(api.get_historial(db=db, _=USER)["snapshots"]) == 2


def test_guardar_y_leer_pagado(db):
    db.add(GarantiaPagado(anio=2026, mes=8, valor=80_000_000.0))
    db.commit()
    leido = db.query(GarantiaPagado).one()
    assert leido.anio == 2026 and float(leido.valor) == 80_000_000.0


def test_set_y_pagado_por_periodo(db):
    set_pagado(db, 2026, 8, 80_000_000.0)
    set_pagado(db, 2026, 8, 75_000_000.0)  # upsert: reemplaza
    d = pagado_por_periodo(db)
    assert d[(2026, 8)] == 75_000_000.0


def test_construir_live_incluye_saldo(db, monkeypatch):
    bal = {"balance": {"ungg": {
        "venta_bolsa": {"real": 0.0, "proyectado": 30.0, "total": 50.0, "n_plantas": 1},
        "compra_bolsa_directa": {"real": 0.0, "proyectado": 4.0, "total": 6.0, "n_plantas": 1},
    }}, "periodo": {}}
    monkeypatch.setattr(svc, "_balance_fn", lambda db_, a, m: bal)
    monkeypatch.setattr(svc, "_precio_fn", lambda: 900.0)
    monkeypatch.setattr(svc, "_regulatorio_fn",
                        lambda a, m: {"valor": 0.0, "anio": a, "mes": m, "fallback": False})
    # garantia resto mes actual = 26*1000*900 = 23_400_000; pagamos 24_000_000 -> saldo +600_000
    set_pagado(db, 2026, 8, 24_000_000.0)
    res = svc.construir_proyecciones_live(db, hoy=date(2026, 8, 14))
    v1 = res["ventanas"][0]
    assert v1["pagado"] == 24_000_000.0
    assert v1["saldo"] == 24_000_000.0 - 23_400_000.0


def test_endpoint_put_y_get_pagado(db):
    api.put_pagado(anio=2026, mes=8, valor=80_000_000.0, db=db, _=USER)
    out = api.get_pagado(db=db, _=USER)
    assert out["pagado"] == [{"anio": 2026, "mes": 8, "valor": 80_000_000.0}]
