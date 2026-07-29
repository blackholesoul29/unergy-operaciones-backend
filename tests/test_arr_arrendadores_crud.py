"""CRUD de arrendadores: crear/listar/editar/eliminar (endpoints de arriendos.py
llamados directamente como funciones, con sesión sqlite en memoria)."""
from datetime import date
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.arriendos import ArrArrendador
from app.schemas.arriendos import ArrArrendadorIn
from app.api.v1.arriendos import listar_arrendadores, crear_arrendador, editar_arrendador, eliminar_arrendador


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ContratoServicio.__table__, ArrArrendador.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _contrato_arriendo(db):
    c = ContratoServicio(servicio_aplica="arriendo", prestador_nombre="Juan Pérez",
                          tarifa_base=51_600_000, fecha_firma_contrato=date(2023, 9, 1))
    db.add(c)
    db.flush()
    return c


def test_crear_y_listar_arrendador(db):
    c = _contrato_arriendo(db)

    creado = crear_arrendador(c.id, ArrArrendadorIn(nombre="María López", valor_base=30_000_000), db=db, _=None)
    assert creado.id is not None
    assert creado.nombre == "María López"

    listado = listar_arrendadores(c.id, db=db, _=None)
    assert len(listado) == 1
    assert listado[0].nombre == "María López"


def test_editar_arrendador(db):
    c = _contrato_arriendo(db)
    creado = crear_arrendador(c.id, ArrArrendadorIn(nombre="María López", valor_base=30_000_000), db=db, _=None)

    editado = editar_arrendador(
        creado.id,
        ArrArrendadorIn(nombre="María López Editado", valor_base=35_000_000, responsable_iva=True),
        db=db, _=None,
    )
    assert editado.nombre == "María López Editado"
    assert float(editado.valor_base) == 35_000_000
    assert editado.responsable_iva is True


def test_eliminar_falla_si_es_el_unico(db):
    c = _contrato_arriendo(db)
    creado = crear_arrendador(c.id, ArrArrendadorIn(nombre="Único", valor_base=1_000_000), db=db, _=None)

    with pytest.raises(HTTPException) as exc_info:
        eliminar_arrendador(creado.id, db=db, _=None)
    assert exc_info.value.status_code == 400


def test_eliminar_funciona_si_hay_dos_o_mas(db):
    c = _contrato_arriendo(db)
    a1 = crear_arrendador(c.id, ArrArrendadorIn(nombre="Uno", valor_base=1_000_000), db=db, _=None)
    crear_arrendador(c.id, ArrArrendadorIn(nombre="Dos", valor_base=2_000_000), db=db, _=None)

    resultado = eliminar_arrendador(a1.id, db=db, _=None)
    assert resultado == {"ok": True}

    restantes = listar_arrendadores(c.id, db=db, _=None)
    assert len(restantes) == 1
    assert restantes[0].nombre == "Dos"
