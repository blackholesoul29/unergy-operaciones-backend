"""Prevencion de duplicados al crear/editar proyectos manualmente:

1. Chequeo proactivo de columnas UNIQUE (sub_project, topic_slug,
   project_id_solenium, sunfactory_project_id) con mensaje accionable.
2. Alerta de nombre muy parecido (match exacto normalizado) antes de crear,
   con opcion de forzar la creacion si de verdad es un proyecto distinto.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.proyectos import (
    ProyectoInversionista, ProyectoInfoTecnica,
    ProyectoInversor,
)
from app.models.contactos import ProyectoAreaContacto, Contacto
from app.models.servicios import ServicioRepresentacion
from app.models.clientes import Cliente
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.contratos import PPAContrato
from app.schemas.proyectos import ProyectoCreate, ProyectoUpdate
from app.api.v1 import proyectos as proyectos_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


# SQLite solo autoincrementa PK de tipo INTEGER (rowid alias); BigInteger no.
# create_proyecto no recibe id (lo genera la BD), asi que aqui SI necesitamos
# que sqlite autoincremente -- a diferencia de otros tests de este repo que
# asignan id a mano.
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, Cliente.__table__, ProyectoInversionista.__table__,
            ProyectoInfoTecnica.__table__,
            ProyectoInversor.__table__, ProyectoAreaContacto.__table__, Contacto.__table__,
            ServicioRepresentacion.__table__,
            # crear_proyecto/actualizar_proyecto ahora hacen
            # selectinload(Proyecto.fronteras).selectinload(Frontera.operador)
            # (ver app/api/v1/proyectos.py) — sin estas dos tablas ese
            # eager load falla con "no such table: fronteras".
            Frontera.__table__, OperadorRed.__table__,
            # ProyectoOut expone `ppa_contratos` (d01e8a9), que se resuelve por
            # la tabla puente: sin ella el eager load falla con
            # "no such table: ppa_contrato_proyectos".
            PPAContrato.__table__, Base.metadata.tables["ppa_contrato_proyectos"],
        Base.metadata.tables["oportunidad_oferta_proyectos"],
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _proyecto(db, **kw):
    p = Proyecto(id=next(_ids), **kw)
    db.add(p)
    db.commit()
    return p


# ── Alerta de nombre parecido ────────────────────────────────────────────────

def test_crear_con_nombre_identico_se_rechaza_sin_forzar(db):
    p = _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")
    data = ProyectoCreate(nombre_comercial="minigranja 0029 - monterrubio")  # mayus/acentos distintos

    with pytest.raises(HTTPException) as exc:
        proyectos_api.create_proyecto(data=data, forzar=False, db=db, _=None)
    assert exc.value.status_code == 409
    # detail estructurado (no un string plano): el frontend lo usa para ofrecer
    # "crear de todos modos" en vez de solo mostrar un toast.
    assert exc.value.detail["duplicado_nombre"] is True
    assert exc.value.detail["candidato_id"] == p.id
    assert "Monterrubio" in exc.value.detail["mensaje"]


def test_crear_con_nombre_identico_se_permite_forzando(db):
    _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")
    data = ProyectoCreate(nombre_comercial="Minigranja 0029 - Monterrubio")

    out = proyectos_api.create_proyecto(data=data, forzar=True, db=db, _=None)
    assert out.nombre_comercial == "Minigranja 0029 - Monterrubio"
    assert db.query(Proyecto).count() == 2


def test_crear_solo_con_el_nombre_de_lugar_se_marca_duplicado(db):
    # Caso real encontrado en produccion: alguien crea "monterrubio" a secas
    # cuando ya existe "Minigranja 0029 - Monterrubio". Un match exacto no lo
    # atrapa; el match por "nombre de lugar" (sin prefijo ni numero) si.
    p = _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")
    data = ProyectoCreate(nombre_comercial="monterrubio")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.create_proyecto(data=data, forzar=False, db=db, _=None)
    assert exc.value.status_code == 409
    assert exc.value.detail["candidato_id"] == p.id


def test_crear_con_nombres_de_fases_distintas_se_marca_como_posible_duplicado(db):
    # "Chinu Sur" y "Chinu Sur 2" son proyectos reales distintos (ver memoria de
    # duplicados), pero comparten "nombre de lugar" una vez se quita el numero.
    # El match permisivo los marca como sugerencia -- no bloquea, se confirma
    # con forzar=true si de verdad es un proyecto distinto (barato de descartar).
    _proyecto(db, nombre_comercial="Minigranja 0059 - Chinu Sur")
    data = ProyectoCreate(nombre_comercial="Minigranja 0060 - Chinu Sur 2")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.create_proyecto(data=data, forzar=False, db=db, _=None)
    assert exc.value.status_code == 409

    out = proyectos_api.create_proyecto(data=data, forzar=True, db=db, _=None)
    assert out.nombre_comercial == "Minigranja 0060 - Chinu Sur 2"


def test_crear_nombre_nuevo_no_se_bloquea(db):
    data = ProyectoCreate(nombre_comercial="Proyecto Totalmente Nuevo")
    out = proyectos_api.create_proyecto(data=data, forzar=False, db=db, _=None)
    assert out.id is not None


# ── Columnas UNIQUE (project_id_solenium / sunfactory_project_id / etc.) ─────

def test_crear_con_sunfactory_project_id_repetido_se_rechaza(db):
    _proyecto(db, nombre_comercial="Proyecto A", sunfactory_project_id=106)
    data = ProyectoCreate(nombre_comercial="Proyecto B", sunfactory_project_id=106)

    with pytest.raises(HTTPException) as exc:
        proyectos_api.create_proyecto(data=data, forzar=True, db=db, _=None)
    assert exc.value.status_code == 409
    assert "Sun Factory" in exc.value.detail


def test_editar_con_project_id_solenium_repetido_se_rechaza(db):
    _proyecto(db, nombre_comercial="Proyecto A", project_id_solenium="500")
    p2 = _proyecto(db, nombre_comercial="Proyecto B")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.update_proyecto(
            id=p2.id, data=ProyectoUpdate(project_id_solenium="500"), db=db, _=None,
        )
    assert exc.value.status_code == 409
    assert "Solenium" in exc.value.detail


def test_editar_el_mismo_proyecto_no_choca_consigo_mismo(db):
    p = _proyecto(db, nombre_comercial="Proyecto A", sunfactory_project_id=106)
    out = proyectos_api.update_proyecto(
        id=p.id, data=ProyectoUpdate(sunfactory_project_id=106), db=db, _=None,
    )
    assert out.sunfactory_project_id == 106


# ── Confirmar sugerencia de vínculo (fix 2) ──────────────────────────────────

def test_vincular_sunfactory_confirma_el_vinculo(db):
    p = _proyecto(db, nombre_comercial="Minigranja - Monterrubio")
    out = proyectos_api.vincular_sunfactory(
        id=p.id, sunfactory_project_id=106, db=db, _=None,
    )
    assert out.sunfactory_project_id == 106


def test_vincular_sunfactory_rechaza_si_el_id_ya_esta_en_otro_proyecto(db):
    _proyecto(db, nombre_comercial="Proyecto A", sunfactory_project_id=106)
    p2 = _proyecto(db, nombre_comercial="Proyecto B")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.vincular_sunfactory(
            id=p2.id, sunfactory_project_id=106, db=db, _=None,
        )
    assert exc.value.status_code == 409


def test_vincular_sunfactory_404_si_no_existe(db):
    with pytest.raises(HTTPException) as exc:
        proyectos_api.vincular_sunfactory(
            id=999999, sunfactory_project_id=106, db=db, _=None,
        )
    assert exc.value.status_code == 404
