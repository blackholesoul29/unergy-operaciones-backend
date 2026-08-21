"""rellenar_horario() -- POST /reporte-energia/fronteras/{id}/rellenar-horario

La curva de referencia del reconectador (curva_reconectador_referencia,
mostrada en ReporteEnergiaCurvaChart.vue) se debe guardar en cuanto el
reconectador respondio con datos, sin importar si alguna de sus horas
termino usandose para rellenar la curva final. Antes solo se guardaba si
el relleno completo tenia exito (raise 400 si no se rellenaba nada),
dejando el reconectador invisible en el chart aunque el dato SI existiera
-- ver reconectador.py:113-116 (2026-08-21).
"""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.api.v1 import reporte_energia as re_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, Frontera.__table__, ReporteEnergiaGeneracion.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


FECHA = date(2026, 8, 1)


def test_curva_reconectador_se_guarda_aunque_nada_se_haya_rellenado(db, monkeypatch):
    db.add(Proyecto(id=1, nombre_comercial="Test", project_id_solenium="123"))
    db.add(Frontera(
        id=1, proyecto_id=1, nombre_frontera="Test",
        tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001",
    ))
    curva_incompleta = [None] * 24
    curva_incompleta[10] = 100.0  # una hora sí tiene dato -- las demás faltan
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=FECHA, caso=1, medidor_usado="cgm",
        curva_final=curva_incompleta, fp=0.9,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    # El reconectador SÍ respondió (curva_reconectador_ref no es None), pero
    # ninguna hora quedó marcada como rellenada por él ni por ninguna otra
    # fuente -- simula sus horas ya cubiertas o fuera de la ventana esperada.
    curva_reconectador_cruda = pd.Series([50.0] * 24)
    monkeypatch.setattr(
        re_api.reconectador, "rellenar_horas_faltantes",
        lambda *a, **kw: (pd.Series(curva_incompleta), set(), set(), set(), curva_reconectador_cruda),
    )

    with pytest.raises(HTTPException) as exc:
        re_api.rellenar_horario(frontera_id=1, fecha=FECHA, db=db, _=None)
    assert exc.value.status_code == 400

    db.refresh(rep)
    assert rep.curva_reconectador_referencia is not None
    assert rep.curva_reconectador_referencia[0] == 50.0


def test_sin_respuesta_del_reconectador_no_guarda_nada(db, monkeypatch):
    db.add(Proyecto(id=1, nombre_comercial="Test", project_id_solenium="123"))
    db.add(Frontera(
        id=1, proyecto_id=1, nombre_frontera="Test",
        tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001",
    ))
    curva_incompleta = [None] * 24
    curva_incompleta[10] = 100.0
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=FECHA, caso=1, medidor_usado="cgm",
        curva_final=curva_incompleta, fp=0.9,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    monkeypatch.setattr(
        re_api.reconectador, "rellenar_horas_faltantes",
        lambda *a, **kw: (pd.Series(curva_incompleta), set(), set(), set(), None),
    )

    with pytest.raises(HTTPException) as exc:
        re_api.rellenar_horario(frontera_id=1, fecha=FECHA, db=db, _=None)
    assert exc.value.status_code == 400

    db.refresh(rep)
    assert rep.curva_reconectador_referencia is None
