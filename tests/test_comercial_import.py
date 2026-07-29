"""Importador de las hojas de prospección → CRM. Harness sqlite; se invoca
`importar_hojas` directamente con un usuario admin stub. Valida forma de la
semilla, que dry_run no escribe, idempotencia y mapeo etapa→resultado."""
import json
import types
from pathlib import Path

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial,
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
        Cliente.__table__, Proyecto.__table__, Oportunidad.__table__,
        OportunidadOferta.__table__, OportunidadEstadoHistorial.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_seed_existe_y_bien_formada():
    data = json.loads(Path("data/comercial_seed.json").read_text(encoding="utf-8"))
    assert len(data) >= 150
    assert {"empresa", "tipo"} <= set(data[0].keys())
    assert {d["tipo"] for d in data} <= {
        "servicios_operacionales", "compra_energia", "comunidad_energetica"}


def test_dry_run_no_escribe(db):
    plan = api.importar_hojas(dry_run=True, db=db, current=ADMIN)
    assert plan["dry_run"] is True
    assert plan["clientes"]["a_crear"] > 0
    assert plan["ofertas"]["creadas"] > 0
    # nada persistido
    assert db.query(Cliente).count() == 0
    assert db.query(OportunidadOferta).count() == 0


def test_import_idempotente(db):
    r1 = api.importar_hojas(dry_run=False, db=db, current=ADMIN)
    assert r1["ofertas"]["creadas"] > 0
    total_ofertas = db.query(OportunidadOferta).count()
    assert total_ofertas == r1["ofertas"]["creadas"]
    # una oportunidad por cliente
    assert db.query(Oportunidad).count() == db.query(Cliente).count()
    # segunda corrida: nada nuevo
    r2 = api.importar_hojas(dry_run=False, db=db, current=ADMIN)
    assert r2["ofertas"]["creadas"] == 0
    assert db.query(OportunidadOferta).count() == total_ofertas


def test_mapeo_etapa_resultado(db):
    api.importar_hojas(dry_run=False, db=db, current=ADMIN)
    aceptadas = db.query(OportunidadOferta).filter_by(etapa_texto="Aprobado").all()
    assert aceptadas and all(o.resultado.value == "aceptado" for o in aceptadas)
    denegadas = db.query(OportunidadOferta).filter_by(etapa_texto="Denegado").all()
    assert denegadas and all(o.resultado.value == "declinado" for o in denegadas)


def test_detalle_servicios_poblado(db):
    api.importar_hojas(dry_run=False, db=db, current=ADMIN)
    serv = [
        o for o in db.query(OportunidadOferta).all()
        if o.tipo.value == "servicios_operacionales" and (o.detalle or {}).get("servicios")
    ]
    assert serv, "esperaba servicios buscados parseados en detalle"
    assert isinstance(serv[0].detalle["servicios"], list) and serv[0].detalle["servicios"]


def test_enriquece_sin_crear(db):
    api.importar_hojas(dry_run=False, db=db, current=ADMIN)
    n = db.query(OportunidadOferta).count()
    # simula "cargado sin detalle" (estado previo al arreglo) y enriquece
    db.query(OportunidadOferta).update({OportunidadOferta.detalle: None})
    db.commit()
    r = api.importar_hojas(dry_run=False, crear_faltantes=False, db=db, current=ADMIN)
    assert r["ofertas"]["creadas"] == 0
    assert r["ofertas"]["faltantes_no_creadas"] == 0        # todas ya existían
    assert db.query(OportunidadOferta).count() == n         # no creó nada
    assert db.query(OportunidadOferta).filter(OportunidadOferta.detalle.isnot(None)).first() is not None


def test_no_admin_rechazado(db):
    no_admin = types.SimpleNamespace(id=2, rol=types.SimpleNamespace(value="comercial"))
    with pytest.raises(Exception):
        api.importar_hojas(dry_run=True, db=db, current=no_admin)
