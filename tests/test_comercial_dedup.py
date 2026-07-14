"""dedup_clientes: fusiona prospectos que el import duplicó contra el cliente
operativo (match planta→dueño / nombre exacto), soft-delete reversible."""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.contratos import ContratoServicio, PPAContrato, ppa_contrato_proyectos_table
from app.models.comercial import Oportunidad, OportunidadOferta, OportunidadEstadoHistorial
from app.api.v1 import comercial as api


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
        Cliente.__table__, Proyecto.__table__, ProyectoInversionista.__table__,
        ContratoServicio.__table__, PPAContrato.__table__, ppa_contrato_proyectos_table,
        Oportunidad.__table__, OportunidadOferta.__table__, OportunidadEstadoHistorial.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _prospecto(db, razon, planta):
    c = Cliente(razon_social_nombre=razon, origen_tipo=None)
    db.add(c)
    db.flush()
    op = Oportunidad(cliente_id=c.id, estado="prospeccion", es_migrada=True)
    db.add(op)
    db.flush()
    db.add(OportunidadOferta(oportunidad_id=op.id, tipo="servicios_operacionales", planta_nombre=planta))
    db.flush()
    return c


@pytest.fixture
def escenario(db):
    # Cliente operativo D dueño de la planta "Naos 1"
    d = Cliente(razon_social_nombre="Naos Generación S.A.S.", origen_tipo="prospeccion_propia")
    db.add(d)
    db.flush()
    p = Proyecto(id=10, nombre_comercial="Naos 1")
    db.add(p)
    db.flush()
    db.add(ProyectoInversionista(proyecto_id=10, cliente_id=d.id))
    # Prospecto duplicado C: su oferta apunta a la planta "Naos 1" (dueño = D)
    c = _prospecto(db, "GD EL REMOLINO S.A.S. E.S.P.", "Naos 1")
    # Prospecto genuino E: planta inexistente → sin canónico
    e = _prospecto(db, "Empresa Totalmente Nueva XYZ", "Planta Inexistente")
    db.commit()
    return {"d": d.id, "c": c.id, "e": e.id}


def test_dry_run_identifica_no_borra(db, escenario):
    r = api.dedup_clientes(dry_run=True, db=db, current=ADMIN)
    assert r["prospectos"] == 2
    assert r["fusionados"] == 1
    assert r["sin_canonico"] == 1
    assert db.query(Cliente).filter(Cliente.id == escenario["c"], Cliente.deleted_at.isnot(None)).first() is None


def test_fusiona_y_reasigna(db, escenario):
    api.dedup_clientes(dry_run=False, db=db, current=ADMIN)
    # C soft-deleted
    c = db.query(Cliente).filter(Cliente.id == escenario["c"]).first()
    assert c.deleted_at is not None
    # la oferta quedó bajo una oportunidad del canónico D, con proyecto_id enlazado
    of = db.query(OportunidadOferta).filter(OportunidadOferta.planta_nombre == "Naos 1").first()
    d_op = db.query(Oportunidad).filter(Oportunidad.id == of.oportunidad_id).first()
    assert d_op.cliente_id == escenario["d"]
    assert of.proyecto_id == 10
    # E (genuino) intacto
    e = db.query(Cliente).filter(Cliente.id == escenario["e"]).first()
    assert e.deleted_at is None
    # idempotente: segunda corrida no fusiona nada
    r2 = api.dedup_clientes(dry_run=False, db=db, current=ADMIN)
    assert r2["fusionados"] == 0


def test_match_difuso_por_tokens(db):
    # Operativo dueño de "GD Naos 4"; prospecto con planta "Naos 4" (sin 'GD').
    d = Cliente(razon_social_nombre="Naos 4 S.A.S.", origen_tipo="referido")
    db.add(d)
    db.flush()
    p = Proyecto(id=44, nombre_comercial="GD Naos 4")
    db.add(p)
    db.flush()
    db.add(ProyectoInversionista(proyecto_id=44, cliente_id=d.id))
    c = _prospecto(db, "Empresa X", "Naos 4")
    db.commit()
    r = api.dedup_clientes(dry_run=False, db=db, current=ADMIN)
    assert r["fusionados"] == 1
    assert db.query(Cliente).filter(Cliente.id == c.id).first().deleted_at is not None


def test_generico_no_fusiona(db):
    # Nova vs Vega comparten solo palabras genéricas (granja/solar) → NO fusiona.
    d = Cliente(razon_social_nombre="Granja Solares Nova", origen_tipo="referido")
    db.add(d)
    db.flush()
    p = Proyecto(id=71, nombre_comercial="Granja Solar Nova I")
    db.add(p)
    db.flush()
    db.add(ProyectoInversionista(proyecto_id=71, cliente_id=d.id))
    c = _prospecto(db, "Empresa Vega", "Granja Solar Vega 2")
    db.commit()
    r = api.dedup_clientes(dry_run=False, db=db, current=ADMIN)
    assert r["fusionados"] == 0
    assert r["sin_canonico"] == 1
    assert db.query(Cliente).filter(Cliente.id == c.id).first().deleted_at is None
