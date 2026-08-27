"""Matching de nombres de portafolio -- auditoría de Proyectos 2026-08-27.

Antes: siembra automática y creación/renombrado manual comparaban nombres
EXACTOS (case-insensitive) -- "FONSAR S.A.S." y "Fonsar SAS" (mismo cliente,
razón social escrita distinto) terminaban en dos portafolios separados, y
crear/renombrar a mano no avisaba de nombres parecidos como sí existe para
Proyecto. Ahora usa el mismo algoritmo de solapamiento de tokens + similitud
de texto (app/utils/nombre_matching.py) para las dos cosas.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto, Cliente, ProyectoInversionista
from app.models.proyectos import Portafolio
from app.api.v1 import portafolios as portafolios_api
from app.api.v1.portafolios import PortafolioCreate, PortafolioUpdate


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto_con_inversionista(db, proyecto_id, cliente_nombre):
    cliente = db.query(Cliente).filter_by(razon_social_nombre=cliente_nombre).first()
    if not cliente:
        cliente = Cliente(razon_social_nombre=cliente_nombre)
        db.add(cliente)
        db.flush()
    p = Proyecto(id=proyecto_id, nombre_comercial=f"Proyecto {proyecto_id}",
                estado="en_operacion", tipo_proyecto="minigranja")
    db.add(p)
    db.flush()
    db.add(ProyectoInversionista(proyecto_id=p.id, cliente_id=cliente.id))
    db.commit()
    return p


def test_siembra_agrupa_razones_sociales_parecidas_en_un_solo_portafolio(db):
    _proyecto_con_inversionista(db, 1, "FONSAR S.A.S.")
    _proyecto_con_inversionista(db, 2, "Fonsar SAS")
    _proyecto_con_inversionista(db, 3, "fonsar s a s")

    portafolios_api._seed_portafolios_if_empty(db)

    assert db.query(Portafolio).count() == 1
    proyectos = db.query(Proyecto).all()
    assert len({p.portafolio_id for p in proyectos}) == 1
    assert all(p.portafolio_id is not None for p in proyectos)


def test_siembra_no_mezcla_clientes_realmente_distintos(db):
    _proyecto_con_inversionista(db, 1, "FONSAR S.A.S.")
    _proyecto_con_inversionista(db, 2, "SUNO ACTIVOS SOSTENIBLES S.A.S.")

    portafolios_api._seed_portafolios_if_empty(db)

    assert db.query(Portafolio).count() == 2


def test_crear_portafolio_con_nombre_parecido_da_409_estructurado(db):
    portafolios_api.create_portafolio(PortafolioCreate(nombre="FONSAR S.A.S."), forzar=False, db=db, _=None)

    with pytest.raises(HTTPException) as exc:
        portafolios_api.create_portafolio(PortafolioCreate(nombre="Fonsar SAS"), forzar=False, db=db, _=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True
    assert exc.value.detail["candidato_nombre"] == "FONSAR S.A.S."


def test_crear_forzado_permite_el_nombre_parecido(db):
    portafolios_api.create_portafolio(PortafolioCreate(nombre="FONSAR S.A.S."), forzar=False, db=db, _=None)
    pt2 = portafolios_api.create_portafolio(
        PortafolioCreate(nombre="Fonsar SAS"), forzar=True, db=db, _=None,
    )
    assert db.query(Portafolio).count() == 2
    assert pt2["nombre"] == "Fonsar SAS"


def test_crear_nombre_exactamente_igual_tambien_avisa_como_parecido(db):
    """Ya no hay un chequeo aparte de '==' -- el matching difuso puntúa 1.0
    para un nombre idéntico, así que lo captura igual."""
    portafolios_api.create_portafolio(PortafolioCreate(nombre="FONSAR S.A.S."), forzar=False, db=db, _=None)

    with pytest.raises(HTTPException) as exc:
        portafolios_api.create_portafolio(PortafolioCreate(nombre="FONSAR S.A.S."), forzar=False, db=db, _=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True


def test_renombrar_a_nombre_parecido_da_409_estructurado(db):
    pt1 = portafolios_api.create_portafolio(PortafolioCreate(nombre="FONSAR S.A.S."), forzar=False, db=db, _=None)
    pt2 = portafolios_api.create_portafolio(PortafolioCreate(nombre="SUNO ACTIVOS"), forzar=False, db=db, _=None)

    with pytest.raises(HTTPException) as exc:
        portafolios_api.update_portafolio(
            pt2["id"], PortafolioUpdate(nombre="Fonsar SAS"), forzar=False, db=db, _=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["candidato_id"] == pt1["id"]
