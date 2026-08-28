"""merge_clientes() no movia contratos_servicio (contratante_id/prestador_id/
inversionista_id) -- auditoria de Clientes 2026-08-27. Con el backfill del
mismo dia poblando esos campos por primera vez en produccion, fusionar un
cliente que resultara ser contratante/prestador/inversionista de algun
contrato lo dejaba apuntando al perdedor (soft-deleted, invisible en la UI)
en vez de migrarse al ganador -- mismo patron de "merge que no mueve todas
las tablas relacionadas" ya visto hoy en Proyecto."""
import datetime as dt

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.contratos import ContratoServicio
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

    # merge_clientes() da de baja al perdedor con `deleted_at = NOW()` (SQL
    # crudo) -- NOW() es de Postgres, SQLite no lo tiene.
    @event.listens_for(engine, "connect")
    def _register_now(conn, rec):
        conn.create_function("NOW", 0, lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_fusionar_mueve_contratante_prestador_e_inversionista(db):
    ganador = Cliente(id=1, razon_social_nombre="Ganador")
    perdedor = Cliente(id=2, razon_social_nombre="Perdedor")
    db.add_all([ganador, perdedor])
    db.flush()

    db.add_all([
        ContratoServicio(id=10, servicio_aplica="representacion", contratante_id=2),
        ContratoServicio(id=11, servicio_aplica="cgm", prestador_id=2),
        ContratoServicio(id=12, servicio_aplica="operacion", inversionista_id=2),
    ])
    db.commit()

    api.merge_clientes(ganador_id=1, perdedor_id=2, dry_run=False, db=db, _=ADMIN)

    assert db.get(ContratoServicio, 10).contratante_id == 1
    assert db.get(ContratoServicio, 11).prestador_id == 1
    assert db.get(ContratoServicio, 12).inversionista_id == 1
    assert db.get(Cliente, 2).deleted_at is not None  # soft-delete, nunca fisico


def test_dry_run_reporta_contratos_servicio_a_mover(db):
    ganador = Cliente(id=1, razon_social_nombre="Ganador")
    perdedor = Cliente(id=2, razon_social_nombre="Perdedor")
    db.add_all([ganador, perdedor])
    db.flush()
    db.add(ContratoServicio(id=10, servicio_aplica="representacion", contratante_id=2))
    db.commit()

    reporte = api.merge_clientes(ganador_id=1, perdedor_id=2, dry_run=True, db=db, _=ADMIN)

    movimiento = next(m for m in reporte["movimientos"] if m["tabla"] == "contratos_servicio")
    assert movimiento["a_mover"] == 1
    # dry_run no debe haber tocado nada
    assert db.get(ContratoServicio, 10).contratante_id == 2
