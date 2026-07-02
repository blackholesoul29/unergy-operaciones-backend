"""Reproduccion: al publicar una terminacion, el fecha_fin del PPA salta a una
fecha inesperada si OTRA planta del mismo contrato_interno ya tenia fecha_fin
cargada en su fila 'registro' por un motivo ajeno a una terminacion real (p.ej.
alguien lleno el campo 'Fecha fin' del formulario GESCON pensando que era la
vigencia del registro, no el cierre de la planta).

_auto_terminate asume que fecha_fin != None en una fila registro/modificacion
significa "esta planta ya se termino". Si esa fila nunca paso por una
terminacion real, la asuncion es falsa y el contrato se cierra con una fecha
que no tiene relacion con la terminacion que el usuario acaba de publicar.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1 import asic as asic_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _sol(db, **kw):
    o = AsicSolicitud(id=next(_ids), **kw)
    db.add(o)
    return o


def test_fecha_fin_stray_en_planta_abierta_contamina_el_cierre_del_contrato(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 555-2024",
                       nombre_interno="UNERGY 555-2024", fecha_fin=date(2040, 1, 1))
    db.add(ppa)
    db.flush()

    # Planta A: nunca se termino, pero tiene fecha_fin cargada por error/otro motivo
    # (p.ej. vigencia GESCON), muy lejos en el futuro.
    _sol(db, codigo_sic_contrato="111", contrato_interno="UNERGY 555-2024",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
         fecha_fin=date(2099, 12, 31))
    # Planta B: la que realmente se va a terminar ahora, sigue abierta hasta este punto.
    _sol(db, codigo_sic_contrato="222", contrato_interno="UNERGY 555-2024",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
         fecha_fin=None)
    db.commit()

    # El usuario agrega un nuevo registro: la terminacion real de la planta B.
    term = AsicSolicitud(id=next(_ids), codigo_sic_contrato="222",
                          tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                          estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                          fecha_fin=date(2026, 3, 15))
    db.add(term)
    db.commit()

    asic_api._auto_terminate(db, term)
    db.commit()
    db.refresh(ppa)

    # Lo esperable: la planta A sigue abierta (fecha_fin=None real), asi que el
    # contrato NO deberia cerrarse todavia.
    assert ppa.fecha_fin == date(2040, 1, 1), (
        f"el contrato se cerro con una fecha ajena a la terminacion publicada "
        f"(planta A nunca se termino): quedo en {ppa.fecha_fin}"
    )
