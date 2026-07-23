"""Rediseño Task 4: al facturar, el valor queda congelado y no se recalcula."""
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
from app.models.om import OMSeleccion, IPCTasa
from app.api.v1 import om as api
from app.services.om_calculator import calcular_proyecto


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)
PERIODO = "2026-06"


# ── pura: valor_congelado tiene prioridad ────────────────────────────────────

def _calc(valor_congelado):
    return calcular_proyecto(
        contrato_id=1, nombre_proyecto="D", fecha_firma_contrato=date(2020, 1, 1),
        fecha_inicio_om=None, valor_base_anual=12_000_000, periodo=PERIODO,
        ipc_tasas={2021: 0.10, 2022: 0.10}, valor_congelado=valor_congelado,
    )


def test_valor_congelado_tiene_prioridad():
    r = _calc(999_999)
    assert r["valor_a_facturar"] == 999_999
    assert r["valor_facturado_congelado"] == 999_999


def test_sin_congelado_recalcula_normal():
    r = _calc(None)
    assert r["valor_facturado_congelado"] is None
    assert r["valor_a_facturar"] != 999_999


# ── endpoint: facturar congela el valor calculado ────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ContratoServicio.__table__, OMSeleccion.__table__, IPCTasa.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_toggle_facturado_congela_el_valor(db):
    c = ContratoServicio(servicio_aplica="mantenimiento", prestador_nombre="P",
                         tarifa_base=12_000_000, fecha_firma_contrato=date(2020, 1, 1))
    db.add(c)
    db.flush()

    sel = api.toggle_facturado(PERIODO, c.id, db=db, _=ADMIN)
    assert sel.facturado is True
    assert sel.valor_facturado_congelado is not None
    assert int(sel.valor_facturado_congelado) == 1_000_000   # 12.000.000 / 12, sin IPC
