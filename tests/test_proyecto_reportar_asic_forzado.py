"""Limpieza automática de Proyecto.reportar_asic_forzado.

La excepción deja de hacer falta en cuanto el proyecto ya cumple srv_cgm
Y (en_operacion O ya se ve generando de verdad, mismo criterio que
'generando_actual' en fronteras.py) -- dejarla prendida sin propósito solo
confunde (decidido 2026-08-21). Se apaga sola tanto desde el PATCH general
(update_proyecto) como desde el toggle de servicios (toggle_servicios),
porque srv_cgm se puede activar por cualquiera de los dos caminos.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.proyectos import ProyectoInversionista, ProyectoInfoTecnica, ProyectoInversor, EstadoProyectoEnum
from app.models.contactos import ProyectoAreaContacto, Contacto
from app.models.servicios import ServicioRepresentacion
from app.models.clientes import Cliente
from app.models.fronteras import Frontera, TipoFronteraEnum, EstadoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.models.operadores_red import OperadorRed
from app.models.contratos import PPAContrato
from app.schemas.proyectos import ProyectoUpdate
from app.api.v1 import proyectos as proyectos_api


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
            Proyecto.__table__, Cliente.__table__, ProyectoInversionista.__table__,
            ProyectoInfoTecnica.__table__, ProyectoInversor.__table__,
            ProyectoAreaContacto.__table__, Contacto.__table__, ServicioRepresentacion.__table__,
            Frontera.__table__, OperadorRed.__table__, ReporteEnergiaGeneracion.__table__,
            PPAContrato.__table__, Base.metadata.tables["ppa_contrato_proyectos"],
            Base.metadata.tables["oportunidad_oferta_proyectos"],
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto(db, **kw):
    p = Proyecto(id=1, nombre_comercial="Test", **kw)
    db.add(p)
    db.commit()
    return p


def test_pasar_a_en_operacion_apaga_la_bandera_si_ya_tiene_cgm(db):
    _proyecto(db, estado=EstadoProyectoEnum.en_desarrollo, srv_cgm=True, reportar_asic_forzado=True)

    out = proyectos_api.update_proyecto(
        1, ProyectoUpdate(estado="en_operacion"), db=db, _=None,
    )
    assert out.estado == "en_operacion"
    assert out.reportar_asic_forzado is False


def test_activar_cgm_via_servicios_apaga_la_bandera_si_ya_esta_en_operacion(db):
    _proyecto(db, estado=EstadoProyectoEnum.en_operacion, srv_cgm=False, reportar_asic_forzado=True)

    out = proyectos_api.toggle_servicios(1, {"srv_cgm": True}, db=db, _=None)
    assert out.srv_cgm is True
    assert out.reportar_asic_forzado is False


def test_no_se_apaga_si_solo_se_cumple_una_condicion(db):
    _proyecto(db, estado=EstadoProyectoEnum.en_desarrollo, srv_cgm=False, reportar_asic_forzado=True)

    # Pasa a en_operacion, pero sigue sin CGM -- la excepcion sigue haciendo falta.
    out = proyectos_api.update_proyecto(1, ProyectoUpdate(estado="en_operacion"), db=db, _=None)
    assert out.reportar_asic_forzado is True


def _con_generacion_real(db, energia_final_kwh):
    front = Frontera(
        id=1, proyecto_id=1, nombre_frontera="F1", tipo_frontera=TipoFronteraEnum.generacion,
        estado=EstadoFronteraEnum.activa, codigo_frontera="frt001",
    )
    db.add(front)
    db.add(ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 21), caso=1,
        energia_final_kwh=energia_final_kwh,
    ))
    db.commit()


def test_se_apaga_si_ya_genera_de_verdad_aunque_estado_no_este_actualizado(db):
    _proyecto(db, estado=EstadoProyectoEnum.en_desarrollo, srv_cgm=True, reportar_asic_forzado=True)
    _con_generacion_real(db, energia_final_kwh=150.0)

    # No se toca 'estado' en este PATCH -- solo un campo cualquiera, para
    # forzar que _limpiar_reportar_asic_forzado_si_ya_no_hace_falta corra.
    out = proyectos_api.update_proyecto(1, ProyectoUpdate(nombre_comercial="Test renombrado"), db=db, _=None)
    assert out.estado == "en_desarrollo"  # sigue sin actualizar a mano
    assert out.reportar_asic_forzado is False


def test_no_se_apaga_por_generacion_en_cero(db):
    _proyecto(db, estado=EstadoProyectoEnum.en_desarrollo, srv_cgm=True, reportar_asic_forzado=True)
    _con_generacion_real(db, energia_final_kwh=0)

    out = proyectos_api.update_proyecto(1, ProyectoUpdate(nombre_comercial="Test renombrado"), db=db, _=None)
    assert out.reportar_asic_forzado is True
