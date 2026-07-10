"""El upsert de informes no debe borrar charts_data cuando el payload lo omite.

Bug real en producción: saveEdit() de InformeDetailView.vue guarda solo
html_content; el upsert pisaba charts_data con None en cada guardado desde la
vista de detalle, borrando los charts del informe.
"""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.models.informes import InformeGuardado
from app.models.usuarios import Usuario
from app.api.v1.informes import InformeUpsertIn, upsert_informe


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


USER = types.SimpleNamespace(id=1, nombre="Tester")

CHARTS = {"rptChartQueue": [{"id": "gen", "type": "bar", "data": [1, 2, 3]}]}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[InformeGuardado.__table__, Usuario.__table__]
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _payload(**overrides):
    base = dict(
        tipo="op",
        sub_project="SP-001",
        periodo_desde="2026-06-01",
        periodo_hasta="2026-06-30",
        html_content="<p>v1</p>",
    )
    base.update(overrides)
    return InformeUpsertIn(**base)


def _crear_con_charts(db):
    return upsert_informe(_payload(charts_data=CHARTS), db=db, current_user=USER)


def test_guardado_sin_charts_data_preserva_los_charts(db):
    inf = _crear_con_charts(db)
    assert inf.charts_data == CHARTS

    # saveEdit() de la vista de detalle: solo cambia html_content
    inf = upsert_informe(_payload(html_content="<p>v2</p>"), db=db, current_user=USER)
    assert inf.html_content == "<p>v2</p>"
    assert inf.charts_data == CHARTS


def test_charts_data_nuevo_si_reemplaza(db):
    _crear_con_charts(db)
    nuevos = {"rptChartQueue": [{"id": "irr", "type": "line", "data": [9]}]}
    inf = upsert_informe(_payload(charts_data=nuevos), db=db, current_user=USER)
    assert inf.charts_data == nuevos


def test_charts_data_como_string_json_se_parsea(db):
    inf = upsert_informe(
        _payload(charts_data='{"rptChartQueue": []}'), db=db, current_user=USER
    )
    assert inf.charts_data == {"rptChartQueue": []}


def test_string_json_invalido_no_borra_los_existentes(db):
    _crear_con_charts(db)
    inf = upsert_informe(
        _payload(charts_data="{no es json"), db=db, current_user=USER
    )
    assert inf.charts_data == CHARTS


def test_creacion_sin_charts_data_queda_null(db):
    inf = upsert_informe(_payload(), db=db, current_user=USER)
    assert inf.charts_data is None
