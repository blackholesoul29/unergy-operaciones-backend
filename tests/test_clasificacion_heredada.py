"""La clasificación NEU/Nitro se hereda del período anterior.

Son plantas muy estables: lo normal es que un proyecto siga siendo NEU mes tras
mes. Exigir que alguien la vuelva a cargar cada mes convierte un olvido en una
liquidación mal armada -- pasó en 2026-07, donde el último registro era de junio
y los cuatro NEU habrían pasado por el camino de la API.

Se hereda la del período más reciente ANTERIOR o igual, así que reclasificar un
mes concreto sigue mandando y no lo pisa la herencia.
"""
import types

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.panel_contable import clasificacion_vigente
from app.models.base import Base
from app.models.panel_contable import ClasificacionLiquidacion
from app.models.proyectos import Proyecto


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Proyecto(id=1, nombre_comercial="MGS 0021 Ibirico", sub_project="ibirico"))
    s.add(Proyecto(id=2, nombre_comercial="MGS 0040 Cacica", sub_project="cacica"))
    s.commit()
    yield s
    s.close()


def _clasificar(db, proyecto_id, periodo, tipo):
    db.add(ClasificacionLiquidacion(proyecto_id=proyecto_id, periodo=periodo, tipo=tipo))
    db.commit()


def test_hereda_del_periodo_anterior(db):
    """El caso que rompió julio: clasificado en junio, nada en julio."""
    _clasificar(db, 1, "2026-06", "neu")
    assert clasificacion_vigente(db, "2026-07")[1] == "neu"


def test_hereda_aunque_haya_varios_meses_de_distancia(db):
    _clasificar(db, 1, "2026-02", "neu")
    assert clasificacion_vigente(db, "2026-09")[1] == "neu"


def test_lo_del_propio_periodo_manda_sobre_lo_heredado(db):
    """Reclasificar un mes concreto no lo puede pisar la herencia."""
    _clasificar(db, 1, "2026-06", "neu")
    _clasificar(db, 1, "2026-07", "nitro")
    assert clasificacion_vigente(db, "2026-07")[1] == "nitro"


def test_volver_a_normal_tambien_se_respeta(db):
    """Si una planta deja de ser NEU, se registra 'normal' y eso manda."""
    _clasificar(db, 1, "2026-06", "neu")
    _clasificar(db, 1, "2026-07", "normal")
    assert clasificacion_vigente(db, "2026-07").get(1, "normal") == "normal"


def test_no_hereda_del_futuro(db):
    """Clasificar agosto no debe cambiar cómo se armó julio."""
    _clasificar(db, 1, "2026-08", "neu")
    assert clasificacion_vigente(db, "2026-07").get(1, "normal") == "normal"


def test_un_proyecto_sin_historia_es_normal(db):
    assert clasificacion_vigente(db, "2026-07").get(2, "normal") == "normal"


def test_cada_proyecto_hereda_lo_suyo(db):
    _clasificar(db, 1, "2026-05", "neu")
    _clasificar(db, 2, "2026-06", "nitro")
    vigente = clasificacion_vigente(db, "2026-07")
    assert vigente[1] == "neu" and vigente[2] == "nitro"


def test_sin_registros_devuelve_vacio(db):
    assert clasificacion_vigente(db, "2026-07") == {}


def test_compara_periodos_como_texto_ordenable(db):
    """'2026-09' < '2026-10' como texto: el formato YYYY-MM lo permite, pero
    '2026-9' rompería el orden. Los períodos se guardan normalizados."""
    _clasificar(db, 1, "2026-09", "neu")
    assert clasificacion_vigente(db, "2026-10")[1] == "neu"
