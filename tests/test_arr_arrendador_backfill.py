"""Backfill idempotente: todo ContratoServicio(arriendo) sin arrendadores
recibe uno automático (nombre=prestador, valor=tarifa_base, responsable_iva=el
del contrato)."""
from datetime import date
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.arriendos import ArrArrendador
from app.main import _backfill_arr_arrendador  # función interna testeable (con db como argumento)


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ContratoServicio.__table__, ArrArrendador.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_crea_arrendador_si_no_existe(db):
    c = ContratoServicio(servicio_aplica="arriendo", prestador_nombre="Juan Pérez",
                          tarifa_base=51_600_000, responsable_iva=True,
                          fecha_firma_contrato=date(2023, 9, 1))
    db.add(c)
    db.flush()

    _backfill_arr_arrendador(db)

    arrendadores = db.query(ArrArrendador).filter(ArrArrendador.contrato_id == c.id).all()
    assert len(arrendadores) == 1
    assert arrendadores[0].nombre == "Juan Pérez"
    assert float(arrendadores[0].valor_base) == 51_600_000
    assert arrendadores[0].responsable_iva is True


def test_no_duplica_si_ya_tiene_arrendador(db):
    c = ContratoServicio(servicio_aplica="arriendo", prestador_nombre="Juan Pérez", tarifa_base=1_000_000)
    db.add(c)
    db.flush()
    db.add(ArrArrendador(contrato_id=c.id, nombre="Ya existe", valor_base=999))
    db.flush()

    _backfill_arr_arrendador(db)

    arrendadores = db.query(ArrArrendador).filter(ArrArrendador.contrato_id == c.id).all()
    assert len(arrendadores) == 1
    assert arrendadores[0].nombre == "Ya existe"


def test_no_afecta_mantenimiento(db):
    c = ContratoServicio(servicio_aplica="mantenimiento", prestador_nombre="Prov Mant", tarifa_base=1_000_000)
    db.add(c)
    db.flush()

    _backfill_arr_arrendador(db)

    assert db.query(ArrArrendador).filter(ArrArrendador.contrato_id == c.id).count() == 0
