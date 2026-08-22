"""_construir_detalle() -- Reconectador en vivo cuando la curva final tiene huecos

Antes "Reconectador" en "Detalle de las fuentes" solo aparecía si alguien
había hecho clic en "Rellenar horas" ese día (única forma de que
curva_reconectador_referencia quedara persistida). Ahora, si la curva
final tiene huecos y no hay nada persistido, se consulta en vivo -- mismo
criterio que ya habilita "Rellenar horas", pero automático, para que el
reconectador aparezca como una fuente más sin depender del clic manual
(pedido 2026-08-21). No se persiste ni toca curva_final -- es solo de
referencia, igual que curva_medidor_.../curva_solenium.
"""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

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


@pytest.fixture(autouse=True)
def _sin_quoia(monkeypatch):
    """Sin credenciales de Quoia en tests -- se fuerza a que GaiaClient()
    falle rápido para que _construir_detalle caiga directo a su
    `except Exception: pass` (el fix bajo prueba no depende de esa parte)."""
    def _raise(*a, **kw):
        raise RuntimeError("sin credenciales Quoia en tests")
    monkeypatch.setattr(re_api, "GaiaClient", _raise)


FECHA = date(2026, 8, 20)


def _setup(db, curva_final, curva_reconectador_referencia=None, project_id_solenium="123"):
    db.add(Proyecto(id=1, nombre_comercial="Test", project_id_solenium=project_id_solenium))
    db.add(Frontera(
        id=1, proyecto_id=1, nombre_frontera="Test",
        tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001",
    ))
    db.add(ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=FECHA, caso=1, medidor_usado="cgm",
        curva_final=curva_final, curva_reconectador_referencia=curva_reconectador_referencia,
    ))
    db.commit()


def test_consulta_en_vivo_si_hay_huecos_y_nada_persistido(db, monkeypatch):
    curva_final = [100.0] * 24
    curva_final[10] = None  # un hueco
    _setup(db, curva_final)

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    llamados = []

    def _fake(sol, id_solenium, fecha_str):
        llamados.append((id_solenium, fecha_str))
        return pd.Series([50.0] * 24)
    monkeypatch.setattr(re_api.reconectador, "get_curva_reconectador", _fake)

    detalle = re_api._construir_detalle(db, frontera_id=1, fecha=FECHA)
    assert llamados == [(123, str(FECHA))]
    assert detalle.curva_reconectador == [50.0] * 24


def test_no_consulta_si_la_curva_final_no_tiene_huecos(db, monkeypatch):
    curva_final = [100.0] * 24  # completa
    _setup(db, curva_final)

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    llamados = []
    monkeypatch.setattr(re_api.reconectador, "get_curva_reconectador", lambda *a, **kw: llamados.append(1))

    detalle = re_api._construir_detalle(db, frontera_id=1, fecha=FECHA)
    assert llamados == []
    assert detalle.curva_reconectador is None


def test_prefiere_lo_persistido_sobre_la_consulta_en_vivo(db, monkeypatch):
    curva_final = [100.0] * 24
    curva_final[10] = None
    _setup(db, curva_final, curva_reconectador_referencia=[77.0] * 24)

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    llamados = []
    monkeypatch.setattr(re_api.reconectador, "get_curva_reconectador", lambda *a, **kw: llamados.append(1))

    detalle = re_api._construir_detalle(db, frontera_id=1, fecha=FECHA)
    assert llamados == []  # ya hay algo persistido, no hace falta consultar
    assert detalle.curva_reconectador == [77.0] * 24


def test_sin_project_id_solenium_no_consulta(db, monkeypatch):
    curva_final = [100.0] * 24
    curva_final[10] = None
    _setup(db, curva_final, project_id_solenium=None)

    monkeypatch.setattr(re_api, "SoleniumClient", lambda: object())
    llamados = []
    monkeypatch.setattr(re_api.reconectador, "get_curva_reconectador", lambda *a, **kw: llamados.append(1))

    detalle = re_api._construir_detalle(db, frontera_id=1, fecha=FECHA)
    assert llamados == []
    assert detalle.curva_reconectador is None
