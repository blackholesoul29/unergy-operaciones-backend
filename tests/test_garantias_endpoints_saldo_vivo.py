"""Cableado de `saldo_vivo_cop` en los endpoints — no solo en el servicio.

Regresión que estos tests atrapan: `_garantia_to_out` tenía un default que degradaba
al valor constituido, así que `PATCH /garantias/{id}` devolvía 100.000.000 en una
garantía que `GET` reportaba agotada (0). El mismo campo, dos verdades. El parámetro
ahora es obligatorio; estos tests fijan el contrato.
"""
import datetime as dt
import sys
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

# El stub de conftest solo define `get_current_user`; el router de garantías también
# importa `_require_admin` para las rutas de escritura.
_auth = sys.modules.get("app.api.v1.auth")
if _auth is not None and not hasattr(_auth, "_require_admin"):
    _auth._require_admin = lambda: None

from app.models.base import Base
import app.models  # noqa: F401
from app.models.garantias import Garantia
from app.schemas.garantias import GarantiaUpdate, MovimientoCreate
from app.api.v1 import garantias as api


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


@pytest.fixture()
def garantia_agotada(db):
    """100M constituidos, agotados por un cobro de XM. Saldo real = 0."""
    g = Garantia(
        tipo="cuenta_custodia",
        valor_cop=100_000_000,
        estado="vigente",
        fecha_vencimiento=HOY + dt.timedelta(days=20),
    )
    db.add(g)
    db.commit()
    # Escribimos el movimiento con el escritor REAL, no a mano.
    api.create_movimiento(
        g.id,
        MovimientoCreate(tipo="cobro_xm", monto_cop=100_000_000, fecha=HOY),
        db=db,
    )
    return g


def test_patch_no_puede_contradecir_al_get(db, garantia_agotada):
    """El bug que bloqueó el QA: editar la garantía resucitaba el valor constituido."""
    g = garantia_agotada

    detalle = api.get_garantia(g.id, db=db)
    # `expiring_days=None` explícito: al llamar la función directa, el default es el
    # objeto `Query` de FastAPI, que solo resuelve el router.
    lista = api.list_garantias(expiring_days=None, db=db)
    item = next(i for i in lista["items"] if i["id"] == g.id)
    patched = api.update_garantia(g.id, GarantiaUpdate(entidad="Bancolombia"), db=db)

    assert detalle["saldo_vivo_cop"] == 0.0
    assert item["saldo_vivo_cop"] == 0.0
    assert patched["saldo_vivo_cop"] == 0.0, "PATCH resucitó el valor constituido"

    # El constituido sigue visible y sin tocar en los tres.
    assert detalle["valor_cop"] == item["valor_cop"] == patched["valor_cop"] == 100_000_000.0


def test_create_garantia_reporta_saldo_vivo(db):
    creada = api.create_garantia(
        api.GarantiaCreate(tipo="poliza", valor_cop=50_000_000, estado="vigente"),
        db=db,
    )
    # Sin movimientos, el saldo vivo es el constituido — pero el campo debe existir.
    assert creada["saldo_vivo_cop"] == 50_000_000.0


def test_resumen_reporta_constituido_y_vivo_por_separado(db, garantia_agotada):
    resumen = api.garantias_resumen(db=db)

    assert resumen["total_valor_cop"] == 100_000_000.0  # constituido
    assert resumen["total_saldo_vivo_cop"] == 0.0       # disponible real
    assert resumen["por_tipo"]["cuenta_custodia"]["saldo_vivo_cop"] == 0.0
    vence = next(x for x in resumen["expiring_30d"] if x["id"] == garantia_agotada.id)
    assert vence["saldo_vivo_cop"] == 0.0


def test_vencimientos_proximos_reporta_saldo_vivo(db, garantia_agotada):
    venc = api.vencimientos_proximos(dias=30, db=db)

    assert venc["valor_total_cop"] == 100_000_000.0
    assert venc["saldo_vivo_total_cop"] == 0.0
    item = next(i for i in venc["buckets"]["30_dias"] if i["id"] == garantia_agotada.id)
    assert item["saldo_vivo_cop"] == 0.0


def test_garantia_to_out_exige_el_saldo(db):
    """Un call site que olvide el saldo debe FALLAR, no inventar un número creíble."""
    g = Garantia(tipo="otro", valor_cop=1_000, estado="vigente")
    db.add(g)
    db.commit()

    with pytest.raises(TypeError):
        api._garantia_to_out(g)
