"""GET /fallas?pendiente_reclasificar=true -- cola de pendientes REALES.

Auditoría 2026-09-02: 833 de 851 fallas `pendiente_reclasificar=True` en
producción vienen de un integrador externo (no vive en este repo, no se
puede tocar su lógica) que reporta diagnósticos eléctricos específicos
(desbalance de tensión, reconectador en cero) pero siempre bajo el subtipo
genérico `red.desconexion_sin_identificar`, sin `alarma_monitoreo_id` (ese
campo solo lo llena el motor MGS interno). Nunca se resuelven vía el flujo
normal de reclasificación. El filtro excluye ese patrón para que la cola
solo muestre lo que de verdad necesita revisión humana.

Límite conocido y aceptado: el patrón (sin alarma_monitoreo_id +
red.desconexion_sin_identificar) es indistinguible de una persona
reportando ese mismo subtipo a mano desde la plataforma -- hoy no hay
ningún caso así en producción, pero si alguna vez lo hay, también quedaría
excluido de la cola."""
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
def base(db):
    db.add(FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta", orden=1, es_estado_final=False))
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=2))
    db.add(Usuario(id=1, nombre="Admin", email="admin@unergy.io",
                   password_hash="x", rol="admin", activo=True))
    db.add(Proyecto(id=10, nombre_comercial="Planta Test", sub_project="PT", estado="en_operacion"))
    db.commit()


def _falla(id, categoria_codigo, subtipo_codigo, alarma_monitoreo_id=None):
    return Falla(
        id=id, codigo_interno=f"FAL-2026-{id:05d}", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="x", fecha_identificacion=HOY,
        categoria_codigo=categoria_codigo, subtipo_codigo=subtipo_codigo,
        pendiente_reclasificar=True, alarma_monitoreo_id=alarma_monitoreo_id,
    )


def test_excluye_el_patron_del_bot_externo(cliente, db, base):
    """alarma_monitoreo_id NULL + red.desconexion_sin_identificar -- la huella
    del integrador externo -- no debe aparecer en la cola de pendientes."""
    db.add(_falla(1, "red", "desconexion_sin_identificar"))
    db.commit()

    r = cliente.get("/api/v1/fallas", params={"pendiente_reclasificar": "true"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_incluye_pendiente_real_de_otra_categoria(cliente, db, base):
    """Una pendiente que no calza con la huella del bot sí debe aparecer."""
    db.add(_falla(2, "generando_sin_datos", "incertidumbre"))
    db.commit()

    r = cliente.get("/api/v1/fallas", params={"pendiente_reclasificar": "true"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == 2


def test_incluye_pendiente_del_motor_mgs_interno(cliente, db, base):
    """Si algún día el motor MGS interno SÍ crea una pendiente estructurada
    (hoy no lo hace), no debe excluirse -- tiene alarma_monitoreo_id real."""
    db.add(_falla(3, "red", "desconexion_sin_identificar", alarma_monitoreo_id=99))
    db.commit()

    r = cliente.get("/api/v1/fallas", params={"pendiente_reclasificar": "true"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == 3


def test_pendiente_reclasificar_false_no_se_ve_afectado_por_la_exclusion(cliente, db, base):
    db.add(Falla(
        id=4, codigo_interno="FAL-2026-00004", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="x", fecha_identificacion=HOY, pendiente_reclasificar=False,
    ))
    db.commit()

    r = cliente.get("/api/v1/fallas", params={"pendiente_reclasificar": "false"})
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_sin_filtro_trae_todas(cliente, db, base):
    db.add(_falla(5, "red", "desconexion_sin_identificar"))
    db.add(_falla(6, "generando_sin_datos", "incertidumbre"))
    db.commit()

    r = cliente.get("/api/v1/fallas")
    assert r.status_code == 200
    assert r.json()["total"] == 2
