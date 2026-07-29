"""tarifa_base de un contrato de arriendo es ANUAL; arr_calculator espera
valor_base MENSUAL — el router debe dividir entre 12 antes de calcular."""
import types
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.arriendos import ArrIPCTasa
from app.api.v1 import arriendos as api


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ContratoServicio.__table__, ArrIPCTasa.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_indexacion_divide_tarifa_base_anual_entre_12(db):
    c = ContratoServicio(servicio_aplica="arriendo", prestador_nombre="P",
                          tarifa_base=51_600_000,  # anual
                          fecha_firma_contrato=date(2023, 9, 1))
    db.add(c)
    db.flush()

    resp = api.indexacion_contrato(c.id, db=db, _=ADMIN)
    # base 2023 (sin IPC aún): mensual = 51.600.000/12 = 4.300.000
    # anual = mensual*12 = 51.600.000 (vuelve al valor original de tarifa_base,
    # confirmando que la división por 12 y la multiplicación interna se cancelan)
    assert resp.mensual[0].valor == 4_300_000
    assert resp.anual[0].valor == 51_600_000
