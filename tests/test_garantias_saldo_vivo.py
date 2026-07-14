"""Saldo vivo de garantías: el valor disponible tras los movimientos, no el constituido.

Regresión de fondo: `create_movimiento` nunca actualiza `Garantia.valor_cop`; el saldo
corriente solo existe en `GarantiaMovimiento.saldo_posterior_cop`. Reportar `valor_cop`
como saldo sobreestima la cobertura y esconde garantías en déficit tras un `cobro_xm`.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.models.garantias import Garantia, GarantiaMovimiento
from app.services.garantias_saldo import saldo_vivo, saldos_posteriores, saldos_vivos


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 7, 14)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _garantia(db, valor_cop, gid=None):
    g = Garantia(
        id=gid,
        tipo="cuenta_custodia",
        valor_cop=valor_cop,
        estado="vigente",
        fecha_vencimiento=HOY + dt.timedelta(days=20),
    )
    db.add(g)
    db.commit()
    return g


def _mov(db, g, tipo, monto, saldo_posterior, fecha):
    m = GarantiaMovimiento(
        garantia_id=g.id,
        tipo=tipo,
        monto_cop=monto,
        saldo_posterior_cop=saldo_posterior,
        fecha=fecha,
    )
    db.add(m)
    db.commit()
    return m


def test_sin_movimientos_el_saldo_vivo_es_el_constituido(db):
    g = _garantia(db, 100_000_000)
    assert saldos_vivos(db, [g]) == {g.id: 100_000_000.0}


def test_cobro_xm_baja_el_saldo_vivo_pero_no_el_valor_constituido(db):
    """El bug real: sin esto, la cobertura se reporta al 100% tras un cobro."""
    g = _garantia(db, 100_000_000)
    _mov(db, g, "cobro_xm", 30_000_000, saldo_posterior=70_000_000, fecha=HOY)

    assert saldos_vivos(db, [g])[g.id] == 70_000_000.0
    db.refresh(g)
    assert float(g.valor_cop) == 100_000_000.0  # el constituido no se toca


def test_ultimo_movimiento_desempata_por_id_como_el_escritor(db):
    """`create_movimiento` ordena por (fecha DESC, id DESC): misma fecha ⇒ gana el id mayor."""
    g = _garantia(db, 50_000_000)
    _mov(db, g, "cobro_xm", 10_000_000, saldo_posterior=40_000_000, fecha=HOY)
    _mov(db, g, "cobro_xm", 15_000_000, saldo_posterior=25_000_000, fecha=HOY)

    assert saldos_vivos(db, [g])[g.id] == 25_000_000.0


def test_movimiento_mas_reciente_por_fecha_gana(db):
    g = _garantia(db, 80_000_000)
    _mov(db, g, "cobro_xm", 20_000_000, saldo_posterior=60_000_000, fecha=HOY)
    _mov(db, g, "deposito", 5_000_000, saldo_posterior=45_000_000, fecha=HOY - dt.timedelta(days=5))

    assert saldos_vivos(db, [g])[g.id] == 60_000_000.0


def test_saldo_posterior_nulo_degrada_al_constituido(db):
    """Filas viejas sin saldo registrado: mismo fallback que usa `create_movimiento`."""
    g = _garantia(db, 40_000_000)
    _mov(db, g, "ajuste", 1_000_000, saldo_posterior=None, fecha=HOY)

    assert saldos_vivos(db, [g])[g.id] == 40_000_000.0


def test_varias_garantias_en_una_sola_query(db):
    g1 = _garantia(db, 10_000_000)
    g2 = _garantia(db, 20_000_000)
    g3 = _garantia(db, 30_000_000)  # sin movimientos
    _mov(db, g1, "cobro_xm", 4_000_000, saldo_posterior=6_000_000, fecha=HOY)
    _mov(db, g2, "cobro_xm", 20_000_000, saldo_posterior=0, fecha=HOY)  # agotada

    saldos = saldos_vivos(db, [g1, g2, g3])
    assert saldos == {g1.id: 6_000_000.0, g2.id: 0.0, g3.id: 30_000_000.0}


def test_garantia_agotada_no_se_reporta_como_cubierta(db):
    """Saldo 0 debe ser 0, no degradar al constituido — es el caso que esconde CRÍTICOS."""
    g = _garantia(db, 25_000_000)
    _mov(db, g, "cobro_xm", 25_000_000, saldo_posterior=0, fecha=HOY)

    assert saldos_vivos(db, [g])[g.id] == 0.0


def test_saldos_posteriores_sin_ids_no_consulta(db):
    assert saldos_posteriores(db, []) == {}


def test_saldo_vivo_unitario():
    assert saldo_vivo(100.0, 70.0, tiene_movimiento=True) == 70.0
    assert saldo_vivo(100.0, None, tiene_movimiento=False) == 100.0
    assert saldo_vivo(100.0, None, tiene_movimiento=True) == 100.0
    assert saldo_vivo(None, None, tiene_movimiento=False) == 0.0
    assert saldo_vivo(100.0, 0.0, tiene_movimiento=True) == 0.0
