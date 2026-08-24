"""Prevencion de duplicados al editar un Operador de Red.

create_operador ya avisaba (409 + `forzar=true`) si el nombre nuevo se
parece mucho a uno existente -- update_operador solo bloqueaba el nombre
*exacto*. Estos tests cubren el mismo aviso ahora tambien al editar."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.operadores_red import OperadorRed, OperadorRedContacto
from app.models.fronteras import Frontera
from app.schemas.operadores_red import OperadorRedUpdate
from app.api.v1 import operadores_red as operadores_red_api


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[OperadorRed.__table__, OperadorRedContacto.__table__, Frontera.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _operador(db, **kw):
    o = OperadorRed(**kw)
    db.add(o)
    db.commit()
    return o


def test_editar_con_nombre_parecido_se_rechaza_sin_forzar(db):
    _operador(db, nombre_legal="Electrificadora del Caribe S.A.S. E.S.P.", nombre_comercial="Afinia")
    otro = _operador(db, nombre_legal="Central Electrica de Narino S.A.")

    with pytest.raises(HTTPException) as exc:
        operadores_red_api.update_operador(
            operador_id=otro.id,
            data=OperadorRedUpdate(nombre_comercial="Afinia"),
            forzar=False, db=db, _=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True


def test_editar_con_nombre_parecido_se_permite_forzando(db):
    _operador(db, nombre_legal="Electrificadora del Caribe S.A.S. E.S.P.", nombre_comercial="Afinia")
    otro = _operador(db, nombre_legal="Central Electrica de Narino S.A.")

    out = operadores_red_api.update_operador(
        operador_id=otro.id,
        data=OperadorRedUpdate(nombre_comercial="Afinia"),
        forzar=True, db=db, _=None,
    )
    assert out.nombre_comercial == "Afinia"


def test_editar_el_mismo_operador_no_choca_consigo_mismo(db):
    op = _operador(db, nombre_legal="Afinia S.A.", nombre_comercial="Afinia")

    out = operadores_red_api.update_operador(
        operador_id=op.id,
        data=OperadorRedUpdate(nombre_comercial="Afinia"),
        forzar=False, db=db, _=None,
    )
    assert out.nombre_comercial == "Afinia"
