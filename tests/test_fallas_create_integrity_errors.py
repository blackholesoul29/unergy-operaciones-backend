"""POST/PATCH /fallas -- errores de integridad legibles en vez de un 500 crudo.

Regresión de un problema ya documentado como deuda conocida en
docs/API_FALLAS.md para los integradores externos: un codigo_legado
repetido (llave de idempotencia) o un FK inexistente (proyecto_id, tipo_id,
estado_id, prioridad_id, resolucion_id, asignado_a_id) volaban como un 500
de Postgres sin mensaje claro. El fix (`_integrity_error_a_http` en
app/api/v1/fallas.py) los traduce a 409/422 con un mensaje legible
(auditoría 2026-09-02)."""
import datetime as dt
import types

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.models.fallas import (
    Falla, FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria,
    FallaCatResolucion, FallaSeguimiento, FallaIntervalo, FallaInversor,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 9, 2)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, Usuario.__table__,
        FallaCatCategoria.__table__, FallaCatTipo.__table__, FallaCatEstado.__table__,
        FallaCatPrioridad.__table__, FallaCatResolucion.__table__,
        Falla.__table__, FallaSeguimiento.__table__, FallaIntervalo.__table__,
        FallaInversor.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def cliente(db):
    from app.core.database import get_db
    from app.api.v1 import fallas as fallas_mod

    app = FastAPI()
    app.include_router(fallas_mod.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[fallas_mod.get_current_user] = lambda: types.SimpleNamespace(
        id=1, nombre="Servicio externo", rol="admin")
    return TestClient(app)


@pytest.fixture
def base(db):
    db.add(FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta", orden=1, es_estado_final=False))
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=2))
    db.add(Usuario(id=1, nombre="Admin", email="admin@unergy.io",
                   password_hash="x", rol="admin", activo=True))
    planta = Proyecto(id=10, nombre_comercial="Planta Test", sub_project="PT", estado="en_operacion")
    db.add(planta)
    db.commit()
    return {"planta": planta}


def _payload(**overrides):
    base = {
        "proyecto_id": 10, "estado_id": 1, "prioridad_id": 1,
        "descripcion": "algo pasó", "fecha_identificacion": HOY.isoformat(),
    }
    base.update(overrides)
    return base


def test_codigo_legado_repetido_da_409_no_500(cliente, base):
    r1 = cliente.post("/api/v1/fallas", json=_payload(codigo_legado="EXT-0001"))
    assert r1.status_code == 201

    r2 = cliente.post("/api/v1/fallas", json=_payload(codigo_legado="EXT-0001"))
    assert r2.status_code == 409
    assert "codigo_legado" in r2.json()["detail"]


def test_creacion_valida_sigue_devolviendo_201(cliente, base):
    r = cliente.post("/api/v1/fallas", json=_payload())
    assert r.status_code == 201
    assert r.json()["codigo_interno"].startswith("FAL-")


# ── _integrity_error_a_http(): la traducción en sí, sin pasar por el
# endpoint completo -- probar un FK inexistente de punta a punta necesitaría
# modelar en SQLite todas las tablas que referencia Proyecto (operadores_red,
# etc.), que es justo lo que este repo evita para tests rápidos. Se prueba
# la función directo, contra mensajes reales de Postgres y de SQLite
# (portable entre los dos, ver _integrity_error_a_http). ──────────────────

def test_integrity_error_fk_inexistente_da_422(monkeypatch):
    from app.api.v1.fallas import _integrity_error_a_http

    postgres_msg = (
        'insert or update on table "fallas" violates foreign key constraint '
        '"fallas_estado_id_fkey"\nDETAIL:  Key (estado_id)=(99999) is not '
        'present in table "fallas_cat_estados".'
    )

    class _Fake(Exception):
        def __str__(self):
            return postgres_msg

    http = _integrity_error_a_http(_Fake())
    assert http.status_code == 422
    assert "no existe" in http.detail


def test_integrity_error_codigo_legado_da_409():
    from app.api.v1.fallas import _integrity_error_a_http

    class _Fake(Exception):
        def __str__(self):
            return ('duplicate key value violates unique constraint '
                     '"uq_fallas_codigo_legado"\nDETAIL:  Key (codigo_legado)=(EXT-0001) already exists.')

    http = _integrity_error_a_http(_Fake())
    assert http.status_code == 409
    assert "codigo_legado" in http.detail


def test_integrity_error_sqlite_fk_da_422():
    """El mismo mensaje pero en el formato que usa SQLite (los tests de este
    repo corren contra SQLite) -- confirma que la detección es portable."""
    from app.api.v1.fallas import _integrity_error_a_http

    class _Fake(Exception):
        def __str__(self):
            return "FOREIGN KEY constraint failed"

    http = _integrity_error_a_http(_Fake())
    assert http.status_code == 422
