"""LiquidacionBatchService: creación en lote de borradores de liquidación.

Verifica el cálculo (generación del mes × tarifa PPA), la idempotencia
(unicidad proyecto+período → segundo lote omite) y el filtrado de proyectos
que no están en operación.
"""
import pytest
from decimal import Decimal
from datetime import date

from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.usuarios import Usuario
from app.models.proyectos import Proyecto
from app.models.contratos import PPAContrato, PPATarifa, ppa_contrato_proyectos_table
from app.models.generacion import GeneracionDiaria
from app.models.liquidaciones import Liquidacion
from app.services.liquidacion_batch_service import LiquidacionBatchService


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


# SQLite solo autoincrementa PK de tipo INTEGER (rowid alias); BigInteger no.
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Usuario.__table__, Proyecto.__table__, PPAContrato.__table__,
            PPATarifa.__table__, ppa_contrato_proyectos_table,
            GeneracionDiaria.__table__, Liquidacion.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _seed(db, *, estado_proyecto="en_operacion", tarifa=Decimal("500.0"),
          year=2025, month=6):
    db.add(Usuario(id=1, email="ops@unergy.io", nombre="Ops", rol="liquidaciones", activo=True))
    p = Proyecto(id=10, nombre_comercial="Minigranja Test",
                 tipo_proyecto="minigranja", estado=estado_proyecto)
    db.add(p)
    c = PPAContrato(id=100, nombre_interno="PPA Test")
    db.add(c)
    db.flush()
    db.execute(ppa_contrato_proyectos_table.insert().values(contrato_id=100, proyecto_id=10))
    if tarifa is not None:
        db.add(PPATarifa(id=1, contrato_id=100, año=year, mes=month, tarifa=tarifa))
    # Generación: 3 días dentro del período + 1 en el mes siguiente y 1 en el
    # anterior (deben quedar EXCLUIDOS por el filtro de rango de fechas).
    gid = 1
    for d, kwh in [(1, 100), (15, 200), (28, 150)]:
        db.add(GeneracionDiaria(id=gid, proyecto_id=10, fecha=date(year, month, d),
                                kwh_real=Decimal(kwh), fuente="test"))
        gid += 1
    db.add(GeneracionDiaria(id=gid, proyecto_id=10, fecha=date(year, month + 1, 3),
                            kwh_real=Decimal("999"), fuente="test"))
    gid += 1
    db.add(GeneracionDiaria(id=gid, proyecto_id=10, fecha=date(year, month - 1, 20),
                            kwh_real=Decimal("888"), fuente="test"))
    db.commit()


def test_crea_borrador_con_ingresos_calculados(db):
    _seed(db)
    res = LiquidacionBatchService().create_monthly_liquidations(db, month=6, year=2025)

    assert len(res) == 1
    r = res[0]
    assert r["status"] == "created"
    assert r["energia_kwh"] == 450.0            # 100 + 200 + 150 (solo junio)
    assert r["ingresos_energia_cop"] == 225000.0  # 450 * 500

    liq = db.query(Liquidacion).one()
    assert liq.estado == "iniciada"
    assert liq.tipo_venta == "ppa"
    assert liq.periodo == date(2025, 6, 1)
    assert liq.generado_por_id == 1
    assert liq.fecha_creacion_automatica is not None
    assert float(liq.ingresos_energia_cop) == 225000.0


def test_idempotente_segundo_lote_omite(db):
    _seed(db)
    svc = LiquidacionBatchService()
    svc.create_monthly_liquidations(db, month=6, year=2025)
    res2 = svc.create_monthly_liquidations(db, month=6, year=2025)

    assert res2[0]["status"] == "skipped_existing"
    assert db.query(Liquidacion).count() == 1  # no se duplicó


def test_proyecto_no_operativo_se_ignora(db):
    _seed(db, estado_proyecto="en_desarrollo")
    res = LiquidacionBatchService().create_monthly_liquidations(db, month=6, year=2025)

    assert res == []
    assert db.query(Liquidacion).count() == 0


def test_sin_tarifa_crea_borrador_sin_ingresos(db):
    _seed(db, tarifa=None)
    res = LiquidacionBatchService().create_monthly_liquidations(db, month=6, year=2025)

    assert res[0]["status"] == "created"
    assert res[0]["ingresos_energia_cop"] is None
    liq = db.query(Liquidacion).one()
    assert liq.ingresos_energia_cop is None


def test_mes_invalido_lanza_error(db):
    with pytest.raises(ValueError):
        LiquidacionBatchService().create_monthly_liquidations(db, month=13, year=2025)
