"""PATCH /fallas/{id} con categoria_codigo: null -- limpiar la clasificación
estructurada de una falla que ya la tenía.

Regresión (auditoría 2026-09-02): el `setattr` que aplica los cambios del
PATCH corre antes de decidir si hay que recalcular la clasificación. El
guard `estructura_touched and falla.categoria_codigo` nunca es cierto
cuando categoria_codigo se está limpiando (ya quedó en None por el propio
setattr), así que `clasificacion`/`subtipo_codigo`/las banderas quedaban
congeladas con el valor viejo, contradiciendo el categoria_codigo=null
recién guardado. El fix agrega una rama explícita que limpia todo lo
derivado en ese caso."""
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
        id=1, nombre="Admin", rol="admin")
    return TestClient(app)


@pytest.fixture
def falla_estructurada(db):
    """Una falla ya clasificada como red.alta_tension, con tipo_id resuelto
    y clasificacion poblada -- el estado "antes" de la limpieza."""
    db.add(FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta", orden=1, es_estado_final=False))
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=2))
    db.add(Usuario(id=1, nombre="Admin", email="admin@unergy.io",
                   password_hash="x", rol="admin", activo=True))
    db.add(Proyecto(id=10, nombre_comercial="Planta Test", sub_project="PT", estado="en_operacion"))
    categoria = FallaCatCategoria(id=1, codigo="red", etiqueta="Red", activa=True)
    db.add(categoria)
    tipo = FallaCatTipo(id=1, categoria_id=1, codigo="red.alta_tension",
                        etiqueta="Alta tensión", activa=True)
    db.add(tipo)
    db.commit()

    falla = Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="Sobretensión detectada", fecha_identificacion=HOY,
        categoria_codigo="red", subtipo_codigo="alta_tension",
        tipo_id=1, pendiente_reclasificar=False,
        clasificacion={"categoria": "red", "categoria_etiqueta": "Red",
                       "subtipo": "alta_tension", "subtipo_etiqueta": "Alta tensión"},
    )
    db.add(falla)
    db.commit()
    return falla


def test_limpiar_categoria_borra_todo_lo_derivado(cliente, db, falla_estructurada):
    r = cliente.patch("/api/v1/fallas/1", json={"categoria_codigo": None})
    assert r.status_code == 200
    body = r.json()

    assert body["categoria_codigo"] is None
    assert body["subtipo_codigo"] is None
    assert body["subtipo_detalle"] is None
    assert body["clasificacion"] is None
    assert body["pendiente_reclasificar"] is False
    assert body["tipo"] is None


def test_limpiar_categoria_no_pisa_tipo_id_si_lo_mandan_en_el_mismo_patch(cliente, db, falla_estructurada):
    """Si el cliente manda tipo_id junto con categoria_codigo:null (pasar la
    falla a modo legacy con un tipo de catálogo), no se debe sobreescribir."""
    tipo_legacy = FallaCatTipo(id=2, categoria_id=1, codigo="9.1", etiqueta="Legacy", activa=True)
    db.add(tipo_legacy)
    db.commit()

    r = cliente.patch("/api/v1/fallas/1", json={"categoria_codigo": None, "tipo_id": 2})
    assert r.status_code == 200
    assert r.json()["tipo"]["id"] == 2


def test_limpiar_categoria_borra_inversores_afectados(cliente, db):
    db.add(FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta", orden=1, es_estado_final=False))
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=2))
    db.add(Usuario(id=1, nombre="Admin", email="admin@unergy.io",
                   password_hash="x", rol="admin", activo=True))
    db.add(Proyecto(id=10, nombre_comercial="Planta Test", sub_project="PT", estado="en_operacion"))
    db.commit()

    falla = Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="Inversor con falla", fecha_identificacion=HOY,
        categoria_codigo="inversores",
        clasificacion={"categoria": "inversores", "categoria_etiqueta": "Inversores", "inversores": []},
    )
    db.add(falla)
    db.commit()
    db.add(FallaInversor(falla_id=1, nombre="Inv1", tipos=["sobre_temperatura"]))
    db.commit()

    r = cliente.patch("/api/v1/fallas/1", json={"categoria_codigo": None})
    assert r.status_code == 200

    restantes = db.query(FallaInversor).filter(FallaInversor.falla_id == 1).count()
    assert restantes == 0


def test_no_limpiar_si_categoria_codigo_no_viene_en_el_payload(cliente, db, falla_estructurada):
    """Un PATCH que no toca categoria_codigo para nada no debe limpiar nada."""
    r = cliente.patch("/api/v1/fallas/1", json={"causa_raiz": "Rayo cercano"})
    assert r.status_code == 200
    body = r.json()
    assert body["categoria_codigo"] == "red"
    assert body["clasificacion"] is not None
