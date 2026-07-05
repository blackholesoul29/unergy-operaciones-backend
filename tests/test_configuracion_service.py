"""Tests de la resolución de configuración operativa (configuracion_service).

Cubren la prioridad específica-de-proyecto > global, la vigencia por fechas /
flag activo, y el comportamiento cuando no hay config (default vs. excepción).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from datetime import datetime, timezone

from app.models.base import Base
from app.models.configuracion_operativa import (
    ConfiguracionOperativa, TipoParametroConfigEnum,
)
from app.services.configuracion_service import (
    obtener_valor, obtener_valor_o_defecto, resolver_configuracion,
    ConfiguracionNoEncontrada, _DEFAULTS,
)

PRECIO = TipoParametroConfigEnum.PRECIO_ENERGIA


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ConfiguracionOperativa.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _cfg(db, **kw):
    kw.setdefault("id", next(_ids))
    kw.setdefault("unidad", "COP/kWh")
    kw.setdefault("fecha_inicio", datetime(2020, 1, 1, tzinfo=timezone.utc))
    kw.setdefault("activo", True)
    c = ConfiguracionOperativa(**kw)
    db.add(c)
    db.commit()
    return c


def test_global_cuando_no_hay_config_de_proyecto(db):
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=800.0)
    # Proyecto sin config propia → debe retornar la global.
    assert obtener_valor(db, PRECIO, proyecto_id=7) == 800.0


def test_config_especifica_tiene_prioridad_sobre_global(db):
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=800.0)
    _cfg(db, proyecto_id=7, tipo_parametro="PRECIO_ENERGIA", valor_float=1500.0)
    assert obtener_valor(db, PRECIO, proyecto_id=7) == 1500.0
    # Otro proyecto sigue viendo la global.
    assert obtener_valor(db, PRECIO, proyecto_id=99) == 800.0


def test_config_inactiva_no_se_usa(db):
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=800.0)
    _cfg(db, proyecto_id=7, tipo_parametro="PRECIO_ENERGIA", valor_float=1500.0, activo=False)
    # La específica está inactiva → cae a la global.
    assert obtener_valor(db, PRECIO, proyecto_id=7) == 800.0


def test_fuera_de_vigencia_por_fecha_fin(db):
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=800.0,
         fecha_inicio=datetime(2020, 1, 1, tzinfo=timezone.utc),
         fecha_fin=datetime(2021, 1, 1, tzinfo=timezone.utc))
    ref = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert resolver_configuracion(db, PRECIO, ref=ref) is None


def test_gana_fecha_inicio_mas_reciente(db):
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=800.0,
         fecha_inicio=datetime(2020, 1, 1, tzinfo=timezone.utc))
    _cfg(db, proyecto_id=None, tipo_parametro="PRECIO_ENERGIA", valor_float=950.0,
         fecha_inicio=datetime(2025, 1, 1, tzinfo=timezone.utc))
    ref = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert obtener_valor(db, PRECIO, ref=ref) == 950.0


def test_sin_config_lanza_excepcion(db):
    with pytest.raises(ConfiguracionNoEncontrada):
        obtener_valor(db, PRECIO, proyecto_id=1)


def test_sin_config_con_default_explicito(db):
    assert obtener_valor(db, PRECIO, proyecto_id=1, default=42.0) == 42.0


def test_obtener_valor_o_defecto_usa_defaults(db):
    assert obtener_valor_o_defecto(db, PRECIO) == _DEFAULTS[PRECIO]
