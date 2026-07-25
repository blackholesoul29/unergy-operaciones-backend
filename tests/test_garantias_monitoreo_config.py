"""PUT /garantias/{id}/monitoreo_config: filtro de nulls explícitos.

Solo `tipo_calculo_cobertura` es nullable; un null explícito en los campos
NOT NULL se ignora (antes pasaba la validación cruzada y reventaba en 500
por IntegrityError). Harness sqlite; se invoca la función del router
directamente (auth stubeada en conftest).
"""
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.garantias import Garantia
from app.api.v1 import garantias as api
from app.schemas.garantia_cobertura import GarantiaMonitoreoConfig


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Garantia.__table__])
    session = sessionmaker(bind=engine)()
    session.add(Garantia(
        id=1, tipo="poliza", valor_cop=1_000_000,
        fecha_vencimiento=datetime.date(2027, 1, 1),
    ))
    session.commit()
    yield session
    session.close()


def _garantia(db):
    return db.query(Garantia).filter(Garantia.id == 1).first()


def test_null_explicito_en_not_null_se_ignora_y_el_resto_aplica(db):
    api.update_monitoreo_config(
        1,
        GarantiaMonitoreoConfig(umbral_alerta_roja=None, monitoreo_cobertura_activo=True),
        db=db,
    )
    g = _garantia(db)
    # el null no tumbó el default NOT NULL; el campo hermano sí se aplicó
    assert float(g.umbral_alerta_roja) == 0.90
    assert g.monitoreo_cobertura_activo is True


def test_campo_nullable_si_acepta_null(db):
    g = _garantia(db)
    g.tipo_calculo_cobertura = "generacion_30d"
    db.commit()

    api.update_monitoreo_config(
        1, GarantiaMonitoreoConfig(tipo_calculo_cobertura=None), db=db,
    )
    assert _garantia(db).tipo_calculo_cobertura is None


def test_validacion_cruzada_sigue_firme_tras_el_filtro(db):
    # roja=0.99 contra la amarilla guardada (0.95) → 422, no 500
    with pytest.raises(HTTPException) as exc:
        api.update_monitoreo_config(
            1, GarantiaMonitoreoConfig(umbral_alerta_roja=0.99), db=db,
        )
    assert exc.value.status_code == 422


def test_null_en_amarilla_no_envenena_la_validacion_cruzada(db):
    # la amarilla null se descarta y la roja se valida contra el valor guardado
    with pytest.raises(HTTPException) as exc:
        api.update_monitoreo_config(
            1,
            GarantiaMonitoreoConfig(umbral_alerta_amarilla=None, umbral_alerta_roja=0.99),
            db=db,
        )
    assert exc.value.status_code == 422


def test_payload_todo_null_es_noop_inofensivo(db):
    api.update_monitoreo_config(
        1,
        GarantiaMonitoreoConfig(
            umbral_alerta_roja=None,
            umbral_alerta_amarilla=None,
            monitoreo_cobertura_activo=None,
        ),
        db=db,
    )
    g = _garantia(db)
    assert float(g.umbral_alerta_roja) == 0.90
    assert float(g.umbral_alerta_amarilla) == 0.95
    assert g.monitoreo_cobertura_activo is False
