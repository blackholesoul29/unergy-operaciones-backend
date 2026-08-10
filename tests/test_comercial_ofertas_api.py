"""API de sub-ofertas del CRM + filtro por tipo de oferta. Harness sqlite;
se invocan las funciones del router directamente con un usuario stub (auth
está stubeado en conftest, así que no hay TestClient con seguridad real)."""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
)
from app.api.v1 import comercial as api
from app.schemas.comercial import (
    OportunidadCreate, OfertaCreate, OfertaUpdate, EstadoChangeIn,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Cliente.__table__, ClienteDocumentoComercial.__table__, Contacto.__table__,
        Proyecto.__table__, Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _crear_oportunidad(db, cliente):
    return api.create_oportunidad(OportunidadCreate(cliente_id=cliente.id), db=db, current=ADMIN)


def test_crud_ofertas(db):
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli); db.flush()
    op = _crear_oportunidad(db, cli)
    oid = op["id"]

    creada = api.create_oferta(oid, OfertaCreate(
        tipo="servicios_operacionales", planta_nombre="P1",
        numero_oferta="OF.REPCGM-001", estado="firmado"), db=db, current=ADMIN)
    ofid = creada["id"]
    assert creada["tipo"] == "servicios_operacionales"
    assert creada["estado"] == "firmado"
    # `resultado` ya no se envía: sale de la etapa.
    assert creada["resultado"] == "aceptado"

    detalle = api.get_oportunidad(oid, db=db, current=ADMIN)
    assert len(detalle["ofertas"]) == 1
    assert detalle["resumen_ofertas"]["servicios_operacionales"] == 1

    api.cambiar_estado_oferta(ofid, EstadoChangeIn(estado="declinado"), db=db, current=ADMIN)
    fila = api.list_ofertas(oid, db=db, current=ADMIN)[0]
    assert fila["estado"] == "declinado"
    assert fila["resultado"] == "declinado"

    api.delete_oferta(ofid, db=db, current=ADMIN)
    assert api.list_ofertas(oid, db=db, current=ADMIN) == []


def test_filtro_tipo_servicio_por_oferta(db):
    cli = Cliente(razon_social_nombre="Beta E.S.P.")
    db.add(cli); db.flush()
    op = _crear_oportunidad(db, cli)
    api.create_oferta(op["id"], OfertaCreate(tipo="compra_energia"), db=db, current=ADMIN)

    def _ids(tipo):
        rows = api.list_oportunidades(estado=None, tipo_servicio=tipo, cliente_id=None,
                                      q=None, solo_alerta=False, db=db, current=ADMIN)
        return {r["id"] for r in rows}

    assert op["id"] in _ids("compra_energia")
    assert op["id"] not in _ids("comunidad_energetica")
    # el resumen_ofertas aparece en la lista sin filtro
    todas = api.list_oportunidades(estado=None, tipo_servicio=None, cliente_id=None,
                                   q=None, solo_alerta=False, db=db, current=ADMIN)
    fila = next(r for r in todas if r["id"] == op["id"])
    assert fila["resumen_ofertas"] == {"compra_energia": 1}
