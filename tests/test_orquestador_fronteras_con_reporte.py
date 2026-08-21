"""_fronteras_con_reporte() -- filtro del clasificador diario.

Solo procesa fronteras de proyectos en_operacion + srv_cgm (confirmado con
el equipo 2026-07-28). Excepción: Proyecto.reportar_asic_forzado, para
proyectos que ya tienen frontera registrada en Quoia pero siguen
en_desarrollo/sin CGM contratado y aun asi deben reportarse (ver GD
Isabela, Los Taurus... 2026-08-21).
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


def _proyecto(db, id_, estado, srv_cgm, reportar_asic_forzado=False):
    p = Proyecto(
        id=id_, nombre_comercial=f"Proyecto {id_}", estado=estado,
        srv_cgm=srv_cgm, reportar_asic_forzado=reportar_asic_forzado,
    )
    db.add(p)
    return p


def _frontera(db, id_, proyecto_id, codigo):
    f = Frontera(
        id=id_, proyecto_id=proyecto_id, nombre_frontera=f"Frontera {id_}",
        tipo_frontera=TipoFronteraEnum.generacion, estado=EstadoFronteraEnum.activa,
        codigo_frontera=codigo,
    )
    db.add(f)
    return f


def test_en_operacion_con_cgm_entra(db):
    _proyecto(db, 1, EstadoProyectoEnum.en_operacion, srv_cgm=True)
    _frontera(db, 1, 1, "frt001")
    db.commit()

    resultado = _fronteras_con_reporte(db)
    assert [f.id for f, _ in resultado] == [1]


def test_en_desarrollo_sin_cgm_no_entra(db):
    _proyecto(db, 2, EstadoProyectoEnum.en_desarrollo, srv_cgm=False)
    _frontera(db, 2, 2, "frt002")
    db.commit()

    resultado = _fronteras_con_reporte(db)
    assert resultado == []


def test_en_desarrollo_sin_cgm_pero_forzado_si_entra(db):
    _proyecto(db, 3, EstadoProyectoEnum.en_desarrollo, srv_cgm=False, reportar_asic_forzado=True)
    _frontera(db, 3, 3, "frt003")
    db.commit()

    resultado = _fronteras_con_reporte(db)
    assert [f.id for f, _ in resultado] == [3]


def test_en_operacion_con_cgm_y_ademas_forzado_no_duplica(db):
    _proyecto(db, 4, EstadoProyectoEnum.en_operacion, srv_cgm=True, reportar_asic_forzado=True)
    _frontera(db, 4, 4, "frt004")
    db.commit()

    resultado = _fronteras_con_reporte(db)
    assert len(resultado) == 1
