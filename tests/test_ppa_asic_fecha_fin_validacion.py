"""Validacion de consistencia entre fecha_fin del contrato PPA macro (manual) y
fecha_fin de sus registros GESCON (asic_solicitudes): ninguna planta puede tener
una fecha_fin posterior a la del contrato macro, en ninguna direccion de edicion.
"""
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models import AsicSolicitud, PPAContrato
from app.models.contratos import ppa_contrato_proyectos_table, PPATarifa, PPACompromisoEnergia
from app.models.proyectos import Proyecto
from app.models.clientes import Cliente
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.schemas.asic import AsicSolicitudUpdate
from app.schemas.ppa import PPAContratoUpdate
from app.api.v1 import asic as asic_api
from app.api.v1 import ppa as ppa_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, Cliente.__table__, AsicSolicitud.__table__,
            PPAContrato.__table__, PPATarifa.__table__, PPACompromisoEnergia.__table__,
            ppa_contrato_proyectos_table,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _ppa(db, numero, fecha_fin):
    c = PPAContrato(id=next(_ids), numero_codigo_contrato=numero, nombre_interno=numero,
                     fecha_fin=fecha_fin)
    db.add(c)
    db.commit()
    return c


def test_crear_registro_gescon_con_fecha_fin_posterior_al_ppa_se_rechaza(db):
    # NOTA: se ejercita _validar_fecha_fin_vs_ppa directamente (en vez de pasar por
    # create_solicitud) porque SQLite no autoincrementa BigInteger PK sin id explícito,
    # y el resto de la suite ya asigna ids a mano por esta misma razón.
    _ppa(db, "UNERGY 001-2023", date(2026, 12, 31))
    sol = AsicSolicitud(id=next(_ids), tipo_solicitud=TipoSolicitudAsicEnum.registro,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         codigo_sic_contrato="111", contrato_interno="UNERGY 001-2023",
                         fecha_fin=date(2027, 1, 15))
    with pytest.raises(HTTPException) as exc:
        asic_api._validar_fecha_fin_vs_ppa(db, sol)
    assert exc.value.status_code == 422
    assert "UNERGY 001-2023" in str(exc.value.detail)


def test_crear_registro_gescon_con_fecha_fin_dentro_del_ppa_se_acepta(db):
    _ppa(db, "UNERGY 002-2023", date(2026, 12, 31))
    sol = AsicSolicitud(id=next(_ids), tipo_solicitud=TipoSolicitudAsicEnum.registro,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         codigo_sic_contrato="222", contrato_interno="UNERGY 002-2023",
                         fecha_fin=date(2026, 1, 15))
    asic_api._validar_fecha_fin_vs_ppa(db, sol)  # no debe lanzar


def test_editar_registro_gescon_a_fecha_fin_posterior_al_ppa_se_rechaza(db):
    ppa = _ppa(db, "UNERGY 003-2023", date(2026, 12, 31))
    sol = AsicSolicitud(id=next(_ids), tipo_solicitud=TipoSolicitudAsicEnum.registro,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         codigo_sic_contrato="333", contrato_ppa_id=ppa.id, fecha_fin=None)
    db.add(sol)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        asic_api.patch_solicitud(
            id=sol.id, data=AsicSolicitudUpdate(fecha_fin=date(2027, 6, 1)), db=db, _=None,
        )
    assert exc.value.status_code == 422


def test_achicar_fecha_fin_del_ppa_por_debajo_de_un_registro_gescon_se_rechaza(db):
    ppa = _ppa(db, "UNERGY 004-2023", date(2039, 12, 31))
    db.add(AsicSolicitud(id=next(_ids), tipo_solicitud=TipoSolicitudAsicEnum.registro,
                          estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                          codigo_sic_contrato="444", contrato_ppa_id=ppa.id,
                          fecha_fin=date(2030, 1, 1)))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        ppa_api.update_contrato(
            id=ppa.id, data=PPAContratoUpdate(fecha_fin=date(2025, 1, 1)), db=db, _=None,
        )
    assert exc.value.status_code == 422


def test_achicar_fecha_fin_del_ppa_por_encima_de_todos_los_registros_se_acepta(db):
    ppa = _ppa(db, "UNERGY 005-2023", date(2039, 12, 31))
    db.add(AsicSolicitud(id=next(_ids), tipo_solicitud=TipoSolicitudAsicEnum.registro,
                          estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                          codigo_sic_contrato="555", contrato_ppa_id=ppa.id,
                          fecha_fin=date(2030, 1, 1)))
    db.commit()

    out = ppa_api.update_contrato(
        id=ppa.id, data=PPAContratoUpdate(fecha_fin=date(2031, 1, 1)), db=db, _=None,
    )
    assert out["fecha_fin"] == "2031-01-01"
