"""Matching y backfill de arr_proyectos → proyectos por nombre/código (fill-if-null, no destructivo)."""
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
from app.models import Proyecto
from app.models.arriendos import ArrProyecto
from app.services.arr_link import normaliza, match_proyecto, backfill_arr_proyecto_links


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__, ArrProyecto.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_normaliza_quita_acentos_y_minusculas():
    assert normaliza("Minigranja Solar Perijá") == "minigranja solar perija"


def test_match_por_nombre_token():
    proyectos = [
        Proyecto(id=1, nombre_comercial="MiniGranja 0016 - La Puya", estado="en_operacion"),
        Proyecto(id=2, nombre_comercial="MiniGranja 0019 - El Merengue", estado="en_operacion"),
    ]
    m = match_proyecto("Minigranja Solar La Puya", None, proyectos)
    assert m is not None and m.id == 1


def test_match_ambiguo_devuelve_none():
    proyectos = [
        Proyecto(id=1, nombre_comercial="Chiriguana 2", estado="en_operacion"),
        Proyecto(id=2, nombre_comercial="Chiriguana 4", estado="en_operacion"),
    ]
    # "Chiriguana" sin número no debe resolver a uno solo
    assert match_proyecto("Minigranja Solar Chiriguana", None, proyectos) is None


def test_backfill_no_sobreescribe_existente(db):
    db.add(Proyecto(id=1, nombre_comercial="MiniGranja 0016 - La Puya", estado="en_operacion"))
    db.add(Proyecto(id=2, nombre_comercial="MiniGranja 0099 - Otra", estado="en_operacion"))
    db.add(ArrProyecto(id=10, nombre="Minigranja Solar La Puya", proyecto_id=None, activo=True))
    db.add(ArrProyecto(id=11, nombre="Ya Vinculada", proyecto_id=2, activo=True))
    db.commit()

    reporte = backfill_arr_proyecto_links(db)

    assert db.query(ArrProyecto).get(10).proyecto_id == 1   # rellenado
    assert db.query(ArrProyecto).get(11).proyecto_id == 2   # intacto
    assert reporte["vinculados"] == 1
    assert reporte["ya_tenian"] == 1
