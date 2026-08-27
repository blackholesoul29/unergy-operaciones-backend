"""El servicio devuelve la forma exacta que el frontend en producción ya consume.

Las claves de estos diccionarios están cableadas en los .vue del plan 1. Un rename acá
no rompe ninguna importación: rompe la tab en silencio. Por eso se asertan por nombre.
"""
import datetime

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.base import Base
from app.models.garantias_modelo import (
    GarCalculo, GarComponentePred, GarComponenteReal,
)
from app.services.garantias_modelo.servicio import construir_detalle, construir_plan

EXPOSICION = "exposicion energia en bolsa ($)"


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_int(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[GarCalculo.__table__, GarComponenteReal.__table__,
                GarComponentePred.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _calculo(db, *, esquema="semanal", vto=(2026, 8, 28), ini=(2026, 8, 1),
             fin=(2026, 8, 7), pred=None, real=None):
    c = GarCalculo(
        agente="UNGG", esquema=esquema,
        fecha_vencimiento=datetime.date(*vto),
        fecha_calculo=datetime.date(2026, 8, 21),
        periodo_ini=datetime.date(*ini), periodo_fin=datetime.date(*fin),
        etiqueta_periodo="AJUSTE TX2",
    )
    db.add(c)
    db.flush()
    if pred is not None:
        db.add(GarComponentePred(calculo_id=c.id, componente=EXPOSICION,
                                 horizonte_dias=7, cuantil=0.9, valor=pred,
                                 modelo_version="replica-1"))
    if real is not None:
        db.add(GarComponenteReal(calculo_id=c.id, componente=EXPOSICION, valor=real))
    db.flush()
    return c


def test_plan_vacio_no_revienta(db):
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=4)
    assert r["semanales"] == []
    assert r["totales"]["suma_p90"] == 0.0


def test_plan_semanal_trae_las_claves_del_contrato(db):
    _calculo(db, pred=13_000_000, real=13_050_000)
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=4)
    assert len(r["semanales"]) == 1
    f = r["semanales"][0]
    for k in ("id", "vencimiento", "periodo_ini", "periodo_fin", "etiqueta_periodo",
              "estado", "central", "p90", "real", "fecha_calculo_xm",
              "procedencia_ventana"):
        assert k in f, f"falta la clave {k} que el frontend lee"
    assert f["id"] == "2026-08-28|2026-08-01"
    assert f["estado"] == "firme"
    assert f["central"] is None          # sin estimador no hay central, y no se finge
    assert f["p90"] == pytest.approx(13_000_000)


def test_plan_mensual_trae_sus_propias_claves(db):
    _calculo(db, esquema="mensual", pred=88_000_000)
    r = construir_plan(db, agente="UNGG", esquema="mensual", cuantil=0.9, horizonte=4)
    assert len(r["mensuales"]) == 1
    m = r["mensuales"][0]
    for k in ("id", "mes", "estado", "central", "p90", "ventana_cierra", "objetivo",
              "publica_xm", "dias_ventaja", "procedencia_ventana"):
        assert k in m, f"falta la clave {k} que el frontend lee"
    assert m["mes"] == "2026-08"


def test_el_esquema_filtra(db):
    _calculo(db, esquema="semanal", pred=1.0)
    _calculo(db, esquema="mensual", ini=(2026, 7, 1), fin=(2026, 7, 31), pred=2.0)
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=4)
    assert len(r["semanales"]) == 1
    assert r["mensuales"] == []


def test_otro_agente_no_aparece(db):
    c = _calculo(db, pred=5.0)
    c.agente = "UNGC"
    db.flush()
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=4)
    assert r["semanales"] == []


def test_suma_p90_ignora_los_nulos(db):
    _calculo(db, pred=10.0)
    _calculo(db, ini=(2026, 8, 8), fin=(2026, 8, 14))   # sin pred
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=4)
    assert len(r["semanales"]) == 2
    assert r["totales"]["suma_p90"] == pytest.approx(10.0)


def test_horizonte_limita_las_filas(db):
    for d in range(1, 8):
        _calculo(db, vto=(2026, 8, 28), ini=(2026, 8, d), fin=(2026, 8, d), pred=1.0)
    r = construir_plan(db, agente="UNGG", esquema="semanal", cuantil=0.9, horizonte=1)
    assert len(r["semanales"]) == 3        # horizonte * 3


def test_detalle_devuelve_la_cadena(db):
    _calculo(db, pred=13_000_000, real=13_050_000)
    r = construir_detalle(db, id="2026-08-28|2026-08-01")
    assert len(r["cadena"]) == 2
    assert r["cadena"][0]["p90"] == pytest.approx(13_000_000)
    assert r["cadena"][1]["p90"] == pytest.approx(13_050_000)


def test_detalle_de_id_inexistente_devuelve_vacio_no_error(db):
    r = construir_detalle(db, id="2030-01-01|2030-01-01")
    assert r["cadena"] == []


def test_detalle_de_id_malformado_no_revienta(db):
    """El id viaja en la URL: un valor basura no puede tumbar el endpoint."""
    for basura in ("", "sin-separador", "no-es-fecha|tampoco", "2026-08-28"):
        r = construir_detalle(db, id=basura)
        assert r["cadena"] == []
