"""_upsert_consumo() (orquestador.py) -- persiste curva_respaldo_final/
respaldo_final_origen, mismo mecanismo que _upsert_generacion (extendido a
Consumo 2026-08-26, pedido de Sara)."""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaConsumo
from app.services.reporte_energia.orquestador import _upsert_consumo


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Frontera.__table__, ReporteEnergiaConsumo.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _frontera(db, id_=1):
    front = Frontera(id=id_, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.consumo_auxiliar, codigo_frontera="frt001")
    db.add(front)
    db.commit()
    return front


def test_respaldo_dentro_de_tolerancia_persiste_medidor(db):
    _frontera(db)
    principal = [10.0] * 24
    respaldo = [10.0] * 23 + [11.0]  # +1 kWh -- dentro de tolerancia
    resultado = {
        "caso": "Medidor", "medidor_usado": "principal",
        "curva_final": pd.Series(principal, dtype=float),
        "curva_medidor_principal": principal, "curva_medidor_respaldo": respaldo,
    }
    _upsert_consumo(db, frontera_id=1, fecha=date(2026, 8, 20), resultado=resultado)
    db.commit()

    fila = db.execute(select(ReporteEnergiaConsumo)).scalar_one()
    assert fila.respaldo_final_origen == "medidor"
    assert fila.curva_respaldo_final == respaldo


def test_respaldo_fuera_de_tolerancia_persiste_estimado(db):
    _frontera(db)
    principal = [10.0] * 24
    respaldo = [10.0] * 23 + [50.0]  # muy lejos -- fuera de tolerancia
    resultado = {
        "caso": "Medidor", "medidor_usado": "principal",
        "curva_final": pd.Series(principal, dtype=float),
        "curva_medidor_principal": principal, "curva_medidor_respaldo": respaldo,
    }
    _upsert_consumo(db, frontera_id=1, fecha=date(2026, 8, 20), resultado=resultado)
    db.commit()

    fila = db.execute(select(ReporteEnergiaConsumo)).scalar_one()
    assert fila.respaldo_final_origen == "estimado"


def test_sin_curva_final_no_persiste_respaldo(db):
    """Ej. caso 'Sin dato' -- sin curva_final no hay nada que comparar."""
    _frontera(db)
    resultado = {"caso": "Sin dato", "medidor_usado": "revisar", "curva_final": None}
    _upsert_consumo(db, frontera_id=1, fecha=date(2026, 8, 20), resultado=resultado)
    db.commit()

    fila = db.execute(select(ReporteEnergiaConsumo)).scalar_one()
    assert fila.curva_respaldo_final is None
    assert fila.respaldo_final_origen is None
