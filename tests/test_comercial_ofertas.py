"""Modelo de sub-ofertas del CRM (oportunidad_ofertas) + rename del estado
terminal fin→servicio_operativo. Harness: SQLite en memoria (igual que
test_clientes_panel), ejercitando el ORM directamente."""
import datetime as dt

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos)
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
from app.models.comercial import (
    Oportunidad, OportunidadOferta, EstadoOportunidadEnum,
    TipoOfertaComercialEnum, ResultadoOfertaEnum,
)


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
        tables=[
            Cliente.__table__, Proyecto.__table__,
            Oportunidad.__table__, OportunidadOferta.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_enum_terminal_renombrado():
    # 'fin' ya no existe; el estado terminal es servicio_operativo.
    assert not hasattr(EstadoOportunidadEnum, "fin")
    assert EstadoOportunidadEnum.servicio_operativo.value == "servicio_operativo"


def test_crear_oferta_ligada(db):
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="prospeccion")
    db.add(op)
    db.flush()
    of = OportunidadOferta(
        oportunidad_id=op.id, tipo=TipoOfertaComercialEnum.servicios_operacionales,
        planta_nombre="Planta 1", numero_oferta="OF.REPCGM-001",
        precio_detalle="REP: 6 · CGM: 6", resultado=ResultadoOfertaEnum.aceptado,
        etapa_texto="Aprobado", fecha_oferta=dt.date(2025, 9, 3),
    )
    db.add(of)
    db.commit()
    db.refresh(op)
    assert len(op.ofertas) == 1
    assert op.ofertas[0].tipo.value == "servicios_operacionales"
    assert op.ofertas[0].resultado.value == "aceptado"


def test_default_resultado_pendiente(db):
    cli = Cliente(razon_social_nombre="Beta")
    db.add(cli)
    db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oferta")
    db.add(op)
    db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia")
    db.add(of)
    db.commit()
    db.refresh(of)
    assert of.resultado.value == "pendiente"
