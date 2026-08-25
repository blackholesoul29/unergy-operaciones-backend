"""_fronteras_con_reporte() -- filtro del clasificador diario.

Reporta al ASIC toda frontera activa (nuestro propio control de
desactivación) cuyo codigo_frontera está registrado en Quoia -- Quoia es
la fuente de verdad de qué se debe reportar, no un campo propio de
Proyecto (decidido 2026-08-21, tras encontrar huecos reales en la regla
anterior de Proyecto.estado/srv_cgm).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.proyectos import Proyecto, EstadoProyectoEnum
from app.models.fronteras import Frontera, TipoFronteraEnum, EstadoFronteraEnum
from app.services.reporte_energia.orquestador import _fronteras_con_reporte


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__, Frontera.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto(db, id_, estado=EstadoProyectoEnum.en_operacion, srv_cgm=True):
    p = Proyecto(id=id_, nombre_comercial=f"Proyecto {id_}", estado=estado, srv_cgm=srv_cgm)
    db.add(p)
    return p


def _frontera(db, id_, proyecto_id, codigo, estado=EstadoFronteraEnum.activa):
    f = Frontera(
        id=id_, proyecto_id=proyecto_id, nombre_frontera=f"Frontera {id_}",
        tipo_frontera=TipoFronteraEnum.generacion, estado=estado,
        codigo_frontera=codigo,
    )
    db.add(f)
    return f


def test_registrada_en_quoia_entra_sin_importar_estado_del_proyecto(db):
    _proyecto(db, 1, EstadoProyectoEnum.en_desarrollo, srv_cgm=False)
    _frontera(db, 1, 1, "frt001")
    db.commit()

    resultado = _fronteras_con_reporte(db, {"frt001"})
    assert [f.id for f, _, _ in resultado] == [1]


def test_no_registrada_en_quoia_no_entra_aunque_este_en_operacion(db):
    _proyecto(db, 2, EstadoProyectoEnum.en_operacion, srv_cgm=True)
    _frontera(db, 2, 2, "frt002")
    db.commit()

    resultado = _fronteras_con_reporte(db, {"frt999"})
    assert resultado == []


def test_comparacion_de_codigo_es_case_insensitive(db):
    _proyecto(db, 3, EstadoProyectoEnum.en_operacion, srv_cgm=True)
    _frontera(db, 3, 3, "Frt0000003")
    db.commit()

    resultado = _fronteras_con_reporte(db, {"frt0000003"})
    assert [f.id for f, _, _ in resultado] == [3]


def test_frontera_cancelada_no_entra_aunque_este_en_quoia(db):
    _proyecto(db, 4, EstadoProyectoEnum.en_operacion, srv_cgm=True)
    _frontera(db, 4, 4, "frt004", estado=EstadoFronteraEnum.cancelada)
    db.commit()

    resultado = _fronteras_con_reporte(db, {"frt004"})
    assert resultado == []
