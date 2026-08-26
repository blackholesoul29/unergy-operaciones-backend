"""_datos_proyectos_para_resumen() (reporte_cgm.py api) -- un tipo_frontera
que no encaja ni en "generación" ni en _TIPOS_CONSUMO (ej.
generacion_consumo) no debe quedar silenciosamente sin frt_gen/frt_con en
el resumen de Cliente. 0 fronteras activas tienen este tipo hoy
(2026-08-26) así que es latente, pero si aparece una, debe loguearse en
vez de desaparecer sin rastro (auditoría CGM 2026-08-26, finding #9)."""
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto, ProyectoInfoTecnica
import app.api.v1.reporte_cgm as rc_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Frontera.__table__, Proyecto.__table__, ProyectoInfoTecnica.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_tipo_no_clasificado_loguea_advertencia_y_no_revienta(db, monkeypatch, caplog):
    db.add(Proyecto(id=1, nombre_comercial="Proyecto Mixto"))
    db.add(Frontera(id=1, nombre_frontera="F1", tipo_frontera=TipoFronteraEnum.generacion_consumo,
                     codigo_frontera="frt001", proyecto_id=1))
    db.commit()
    fronteras = db.query(Frontera).all()

    monkeypatch.setattr(rc_api.curvas_energia, "construir_mapa_borders", lambda gaia: {})

    with caplog.at_level(logging.WARNING, logger="reporte_cgm"):
        proyectos = rc_api._datos_proyectos_para_resumen(db, gaia=object(), fronteras=fronteras)

    assert proyectos[1]["frt_gen"] is None
    assert proyectos[1]["frt_con"] is None
    assert any("sin clasificar" in r.message for r in caplog.records)


def test_generacion_y_consumo_siguen_sin_generar_warning(db, monkeypatch, caplog):
    db.add(Proyecto(id=1, nombre_comercial="Proyecto Normal"))
    db.add(Frontera(id=1, nombre_frontera="Gen", tipo_frontera=TipoFronteraEnum.generacion,
                     codigo_frontera="frt001", proyecto_id=1))
    db.add(Frontera(id=2, nombre_frontera="Con", tipo_frontera=TipoFronteraEnum.consumo,
                     codigo_frontera="frt002", proyecto_id=1))
    db.commit()
    fronteras = db.query(Frontera).all()

    monkeypatch.setattr(rc_api.curvas_energia, "construir_mapa_borders", lambda gaia: {})

    with caplog.at_level(logging.WARNING, logger="reporte_cgm"):
        proyectos = rc_api._datos_proyectos_para_resumen(db, gaia=object(), fronteras=fronteras)

    assert proyectos[1]["frt_gen"] == "frt001"
    assert proyectos[1]["frt_con"] == "frt002"
    assert not caplog.records
