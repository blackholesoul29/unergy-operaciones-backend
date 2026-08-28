"""create_cliente(): aviso de nombre parecido (ya existia, pero el frontend
nunca lo conectaba -- auditoria de Clientes 2026-08-27) y manejo de colision
de NIT (nit_cedula es UNIQUE en la BD; el commit no capturaba
IntegrityError, asi que un NIT duplicado reventaba con 500 crudo)."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.schemas.clientes import ClienteCreate
from app.api.v1 import clientes as api

ADMIN = None


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_crear_cliente_con_nombre_parecido_da_409_estructurado(db):
    db.add(Cliente(razon_social_nombre="Quantum Energy Ingenieria S.A.S."))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.create_cliente(ClienteCreate(razon_social_nombre="Quantum"), forzar=False, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True
    assert exc.value.detail["candidato_nombre"] == "Quantum Energy Ingenieria S.A.S."


def test_crear_forzado_permite_el_nombre_parecido(db):
    db.add(Cliente(razon_social_nombre="Quantum Energy Ingenieria S.A.S."))
    db.commit()

    out = api.create_cliente(ClienteCreate(razon_social_nombre="Quantum"), forzar=True, db=db, _=ADMIN)
    assert out.razon_social_nombre == "Quantum"
    assert db.query(Cliente).count() == 2


def test_crear_cliente_con_nit_duplicado_da_409_no_500(db):
    db.add(Cliente(razon_social_nombre="Cliente Uno", nit_cedula="900123456-7"))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.create_cliente(
            ClienteCreate(razon_social_nombre="Cliente Totalmente Distinto", nit_cedula="900123456-7"),
            forzar=True, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 409
