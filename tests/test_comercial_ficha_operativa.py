"""Ficha operativa de la oferta (2026-08-03).

Los 6 parámetros que el equipo consume por API — nombre del proyecto, lugar,
operador de red, energía real, energía promedio, fecha de inicio de operación y
tiempo del contrato — solo existían colgados de `Proyecto`, y la mayoría de las
ofertas del pipeline no tienen proyecto (GD Rio Pamplonita y GD Las Margaritas 1
ni siquiera existen como planta). Lo que se protege aquí es la cascada
Proyecto → declarado en la oferta → null, y que consultarla no cueste una
consulta por oferta.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.generacion import GeneracionDiaria
from app.models.contratos import PPAContrato, PPATarifa, ContratoServicio
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
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
        Proyecto.__table__, Frontera.__table__, OperadorRed.__table__,
        GeneracionDiaria.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ── Task 1: las columnas declaradas ──────────────────────────────────────────

def test_la_oferta_puede_declarar_lugar_operador_y_energia(db):
    """Sin Proyecto no hay dónde poner el lugar ni el operador. Estas cuatro
    columnas son ese lugar: la oferta declara lo que sabe y la API lo resuelve."""
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()

    of = OportunidadOferta(
        oportunidad_id=op.id, tipo="compra_energia",
        planta_nombre="GD Las Margaritas 1",
        municipio="Sincelejo", departamento="Sucre",
        operador_red_id=orr.id, energia_promedio_kwh_mes=185000)
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio == "Sincelejo"
    assert of.departamento == "Sucre"
    assert of.operador_red_id == orr.id
    assert float(of.energia_promedio_kwh_mes) == 185000.0


def test_los_cuatro_campos_son_opcionales(db):
    """Una oferta recién creada no sabe nada de la planta todavía."""
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia")
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio is None and of.departamento is None
    assert of.operador_red_id is None and of.energia_promedio_kwh_mes is None
