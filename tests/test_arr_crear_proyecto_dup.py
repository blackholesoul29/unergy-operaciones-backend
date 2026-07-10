"""crear_proyecto no debe crear un segundo arr_proyecto para el mismo proyecto_id."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
from app.models import Proyecto
from app.models.arriendos import ArrProyecto
from app.models.contratos import ContratoServicio
from app.schemas.arriendos import ArrProyectoIn
from app.api.v1 import arriendos as arr_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, ArrProyecto.__table__, ContratoServicio.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_crear_duplicado_por_proyecto_id_se_rechaza(db):
    db.add(Proyecto(id=1, nombre_comercial="La Puya", estado="en_operacion"))
    db.add(ArrProyecto(id=10, nombre="La Puya", proyecto_id=1, activo=True))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        arr_api.crear_proyecto(ArrProyectoIn(nombre="La Puya", proyecto_id=1), db=db, _=None)
    assert exc.value.status_code == 409


def test_crear_sin_duplicado_ok(db):
    db.add(Proyecto(id=1, nombre_comercial="La Puya", estado="en_operacion"))
    db.commit()
    out = arr_api.crear_proyecto(ArrProyectoIn(nombre="La Puya", proyecto_id=1), db=db, _=None)
    assert out.proyecto_id == 1
    assert db.query(ArrProyecto).count() == 1
