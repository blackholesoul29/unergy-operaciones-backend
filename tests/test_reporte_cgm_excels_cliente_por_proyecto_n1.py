"""_excels_cliente_por_proyecto() (reporte_cgm.py api) -- una sola
resolución de _datos_proyectos_para_resumen() (1 query a ProyectoInfoTecnica)
para TODOS los proyectos del cliente, no una por proyecto.

Antes, con 2+ proyectos (CLIENTES_EXCEL_POR_PROYECTO), el loop llamaba a
_datos_proyectos_para_resumen() una vez por proyecto -- N+1 real, aunque de
bajo impacto hoy (auditoría CGM 2026-08-26, finding #8)."""
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


def test_una_sola_llamada_a_datos_proyectos_para_resumen_para_2_proyectos(db, monkeypatch):
    db.add(Proyecto(id=1, nombre_comercial="Proyecto Uno"))
    db.add(Proyecto(id=2, nombre_comercial="Proyecto Dos"))
    db.add(Frontera(id=1, nombre_frontera="F1", tipo_frontera=TipoFronteraEnum.generacion,
                     codigo_frontera="frt001", proyecto_id=1))
    db.add(Frontera(id=2, nombre_frontera="F2", tipo_frontera=TipoFronteraEnum.generacion,
                     codigo_frontera="frt002", proyecto_id=2))
    db.commit()

    fronteras = db.query(Frontera).all()

    llamadas = []
    original = rc_api._datos_proyectos_para_resumen

    def _spy(db_, gaia_, fronteras_):
        llamadas.append(len(fronteras_))
        return original(db_, gaia_, fronteras_)

    monkeypatch.setattr(rc_api, "_datos_proyectos_para_resumen", _spy)
    monkeypatch.setattr(rc_api.curvas_energia, "construir_mapa_borders", lambda gaia: {})
    monkeypatch.setattr(rc_api.svc, "calcular_resumen_diario", lambda gaia, proyectos, filas_por_frt, dia: [])
    monkeypatch.setattr(rc_api.svc, "generar_excel_cliente", lambda *a, **kw: b"xlsx")

    adjuntos = rc_api._excels_cliente_por_proyecto(
        db, gaia=object(), fronteras=fronteras, filas_por_frt={},
        dias=["2026-08-25"], dias_mes=["2026-08-25"], es_ultimo_dia_mes=False,
        fecha_inicio=__import__("datetime").date(2026, 8, 25), fecha_archivo="2026-08-25",
    )

    assert len(llamadas) == 1  # antes: 2 (una por proyecto)
    assert llamadas[0] == 2  # las 2 fronteras juntas, no una a la vez
    assert len(adjuntos) == 2
