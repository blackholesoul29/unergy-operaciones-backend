"""POST /comercial/backfill: migra clientes sin Oportunidad, vinculando sus
proyectos reales (via ProyectoInversionista) a la Oferta migrada por la M2M
(oportunidad_oferta_proyectos) -- no por Proyecto.oportunidad_id (columna
eliminada, auditoria de Proyectos 2026-08-28: 0/188 poblada, sin otro lector
real que este mismo endpoint)."""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.contratos import ContratoServicio, PPAContrato
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial,
    oportunidad_oferta_proyectos_table,
)
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
        ContratoServicio.__table__, PPAContrato.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, oportunidad_oferta_proyectos_table,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _cliente_con_proyecto(db, razon, proyecto_id):
    c = Cliente(razon_social_nombre=razon, origen_tipo=None)
    db.add(c)
    db.flush()
    p = db.get(Proyecto, proyecto_id)
    if p is None:
        p = Proyecto(id=proyecto_id, nombre_comercial=f"Planta {proyecto_id}")
        db.add(p)
        db.flush()
    db.add(ProyectoInversionista(proyecto_id=proyecto_id, cliente_id=c.id))
    db.flush()
    return c


def test_dry_run_no_escribe_nada(db):
    c = _cliente_con_proyecto(db, "Cliente Sin Oportunidad", proyecto_id=1)
    r = api.backfill(dry_run=True, solo_con_relacion_comercial=False, db=db, current=ADMIN)
    assert r["clientes_a_migrar"] == 1
    assert r["proyectos_a_vincular"] == 1
    assert db.query(Oportunidad).filter(Oportunidad.cliente_id == c.id).first() is None
    assert db.query(OportunidadOferta).count() == 0


def test_backfill_vincula_via_m2m_no_via_columna_proyecto(db):
    """El bug que motivo el fix: antes de esto, la seccion "proyectos
    vinculados" del detalle de Oportunidad (via Oportunidad.proyectos, que
    leia Proyecto.oportunidad_id) siempre daba vacio porque nada la llenaba.
    Confirma que el backfill deja la M2M poblada -- el mismo mecanismo que ya
    usa _plantas_de_ofertas() para esa seccion."""
    c = _cliente_con_proyecto(db, "Cliente Real Sin Oportunidad", proyecto_id=42)
    api.backfill(dry_run=False, solo_con_relacion_comercial=False, db=db, current=ADMIN)

    op = db.query(Oportunidad).filter(Oportunidad.cliente_id == c.id).first()
    assert op is not None
    assert op.estado == "operando"
    assert op.es_migrada is True

    ofertas = db.query(OportunidadOferta).filter(OportunidadOferta.oportunidad_id == op.id).all()
    assert len(ofertas) == 1
    oferta = ofertas[0]
    assert oferta.tipo == "servicios_operacionales"
    assert oferta.estado == "operando"

    pares = db.execute(
        oportunidad_oferta_proyectos_table.select().where(
            oportunidad_oferta_proyectos_table.c.oferta_id == oferta.id)
    ).all()
    assert [p.proyecto_id for p in pares] == [42]


def test_backfill_es_idempotente(db):
    """Correrlo dos veces no duplica: el segundo pase ya no encuentra
    clientes sin Oportunidad."""
    _cliente_con_proyecto(db, "Cliente A", proyecto_id=1)
    api.backfill(dry_run=False, solo_con_relacion_comercial=False, db=db, current=ADMIN)
    r2 = api.backfill(dry_run=False, solo_con_relacion_comercial=False, db=db, current=ADMIN)
    assert r2["clientes_a_migrar"] == 0
    assert db.query(Oportunidad).count() == 1
    assert db.query(OportunidadOferta).count() == 1


def test_cliente_sin_proyectos_igual_recibe_oportunidad(db):
    """Un cliente sin ProyectoInversionista (ej. inversionista sin planta
    propia, o cliente puramente comercial) igual se migra, solo sin ofertas."""
    c = Cliente(razon_social_nombre="Cliente Sin Plantas", origen_tipo=None)
    db.add(c)
    db.flush()
    api.backfill(dry_run=False, solo_con_relacion_comercial=False, db=db, current=ADMIN)
    op = db.query(Oportunidad).filter(Oportunidad.cliente_id == c.id).first()
    assert op is not None
    assert db.query(OportunidadOferta).filter(OportunidadOferta.oportunidad_id == op.id).count() == 0


def test_no_admin_rechazado(db):
    from fastapi import HTTPException
    no_admin = types.SimpleNamespace(id=2, rol=types.SimpleNamespace(value="comercial"))
    with pytest.raises(HTTPException) as exc:
        api.backfill(dry_run=True, db=db, current=no_admin)
    assert exc.value.status_code == 403


def test_solo_con_relacion_comercial_excluye_inversionistas_puros(db):
    """El job diario (_scheduled_comercial_backfill) llama con este flag en
    true: un inversionista puro (sin ContratoServicio ni PPA) nunca paso por
    una negociacion comercial, asi que no se le crea una Oportunidad."""
    inversionista = _cliente_con_proyecto(db, "Inversionista Puro", proyecto_id=1)

    con_contrato = Cliente(razon_social_nombre="Cliente Con Contrato")
    db.add(con_contrato); db.flush()
    db.add(ContratoServicio(contratante_id=con_contrato.id, servicio_aplica="representacion"))

    con_ppa = Cliente(razon_social_nombre="Cliente Con PPA")
    db.add(con_ppa); db.flush()
    db.add(PPAContrato(comprador_id=con_ppa.id, tipo_contrato="venta"))
    db.flush()

    r = api.backfill(dry_run=False, solo_con_relacion_comercial=True, db=db, current=ADMIN)
    assert r["clientes_a_migrar"] == 2

    migrados = {o.cliente_id for o in db.query(Oportunidad).all()}
    assert migrados == {con_contrato.id, con_ppa.id}
