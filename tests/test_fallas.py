"""Tests de _estimar_perdida_falla (estimación financiera de pérdida por falla).

Tras externalizar el precio de energía y el factor solar a
`configuracion_operativa`, el estimador resuelve esos valores vía
`configuracion_service`. Con la tabla vacía cae a los valores de referencia
(_DEFAULTS); con una config específica del proyecto, usa la específica.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from datetime import datetime, timezone

from app.models.base import Base
from app.models.configuracion_operativa import (
    ConfiguracionOperativa, TipoParametroConfigEnum,
)
from app.services.configuracion_service import _DEFAULTS
from app.api.v1.fallas import _estimar_perdida_falla

_SOLAR = _DEFAULTS[TipoParametroConfigEnum.CAPACIDAD_SOLAR]
_PRECIO = _DEFAULTS[TipoParametroConfigEnum.PRECIO_ENERGIA]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ConfiguracionOperativa.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_zero_downtime_is_zero(db):
    assert _estimar_perdida_falla(990, 0, db, None) == (0.0, 0.0)


def test_no_potencia_is_zero(db):
    assert _estimar_perdida_falla(None, 10, db, None) == (0.0, 0.0)


def test_known_value_24h_downtime_usa_defaults(db):
    # Tabla vacía → cae a los valores de referencia.
    # 24h downtime → solar_hours = 12 ; kwh = 990 * 0.18 * 12
    kwh, cop = _estimar_perdida_falla(990, 24, db, None)
    assert kwh == round(990 * _SOLAR * 12, 3)
    assert cop == round(kwh * _PRECIO, 2)


def test_solar_hours_is_half_of_downtime(db):
    # 10h downtime → solar_hours = 5 (≈50% del downtime)
    kwh, _ = _estimar_perdida_falla(100, 10, db, None)
    assert kwh == round(100 * _SOLAR * 5, 3)


def test_config_especifica_de_proyecto_tiene_prioridad(db):
    # Config específica de un proyecto sobreescribe el precio de referencia.
    db.add(ConfiguracionOperativa(
        id=1, proyecto_id=42, tipo_parametro="PRECIO_ENERGIA",
        valor_float=1200.0, unidad="COP/kWh",
        fecha_inicio=datetime(2020, 1, 1, tzinfo=timezone.utc), activo=True,
    ))
    db.commit()
    kwh, cop = _estimar_perdida_falla(990, 24, db, 42)
    assert kwh == round(990 * _SOLAR * 12, 3)
    assert cop == round(kwh * 1200.0, 2)
