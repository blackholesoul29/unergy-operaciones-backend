"""_upsert_generacion() -- curva_reconectador_referencia no debe quedar en
SQL NULL cuando `resultado` no la trae.

Asignar Python None a una columna JSONB con SQLAlchemy guarda el literal
JSON 'null', NO SQL NULL -- por eso `_upsert_generacion` asignaba
fila.curva_reconectador_referencia = resultado.get(...) sin guardia,
dejando la columna "no nula" para básicamente todas las filas (el
clasificador automático nunca pone esa clave en resultado). Eso hacía
inútil cualquier filtro `IS NOT NULL` para encontrar cuáles filas SÍ
tienen un reconectador real guardado (descubierto 2026-08-21, ver
tests/test_reporte_energia_rellenar_horario_reconectador_ref.py).
"""
from datetime import date

import pytest
from sqlalchemy import create_engine, text, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.services.reporte_energia.orquestador import _upsert_generacion


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _biginteger_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ReporteEnergiaGeneracion.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


FECHA = date(2026, 8, 1)


def _valor_crudo(db, rep_id):
    """Lee la columna directo con SQL, sin pasar por el ORM -- un NULL real
    llega como None; el literal JSON 'null' llegaría como el string
    "null"."""
    return db.execute(
        text("SELECT curva_reconectador_referencia FROM reporte_energia_generacion WHERE id = :id"),
        {"id": rep_id},
    ).scalar()


def test_resultado_sin_reconectador_deja_la_columna_en_null_real(db):
    resultado = {"caso": 1, "medidor_usado": "cgm", "curva_final": None}
    _upsert_generacion(db, frontera_id=1, fecha=FECHA, resultado=resultado)
    db.commit()

    rep = db.query(ReporteEnergiaGeneracion).filter(
        ReporteEnergiaGeneracion.frontera_id == 1, ReporteEnergiaGeneracion.fecha == FECHA,
    ).one()
    assert rep.curva_reconectador_referencia is None
    assert _valor_crudo(db, rep.id) is None  # no el string "null"


def test_reclasificar_sin_reconectador_no_pisa_con_null_json(db):
    resultado = {"caso": 1, "medidor_usado": "cgm", "curva_final": None}
    _upsert_generacion(db, frontera_id=1, fecha=FECHA, resultado=resultado)
    db.commit()

    # Segunda corrida (re-ejecutar clasificación el mismo día) -- tampoco
    # trae la clave, pero no debe convertir el NULL real en JSON 'null'.
    _upsert_generacion(db, frontera_id=1, fecha=FECHA, resultado=resultado)
    db.commit()

    rep = db.query(ReporteEnergiaGeneracion).filter(
        ReporteEnergiaGeneracion.frontera_id == 1, ReporteEnergiaGeneracion.fecha == FECHA,
    ).one()
    assert _valor_crudo(db, rep.id) is None
