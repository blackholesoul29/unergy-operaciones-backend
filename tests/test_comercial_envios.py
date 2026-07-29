"""Columnas de envio de la oferta: seguimientos, ultima respuesta y link al PDF.
Harness: SQLite en memoria, igual que test_comercial_ofertas."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.comercial import Oportunidad, OportunidadOferta


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = type("U", (), {"rol": type("R", (), {"value": "admin"})()})()


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _oferta(db):
    c = Cliente(razon_social_nombre="ACME")
    db.add(c)
    db.flush()
    op = Oportunidad(cliente_id=c.id, estado="envio_oferta")
    db.add(op)
    db.flush()
    o = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia",
                          numero_oferta="OP.COM No.0103-6-2026")
    db.add(o)
    db.commit()
    return o


def test_seguimientos_arranca_en_cero(db):
    assert _oferta(db).seguimientos == 0


def test_campos_nuevos_persisten(db):
    o = _oferta(db)
    o.seguimientos = 6
    o.fecha_ultima_respuesta = dt.date(2026, 6, 26)
    o.documento_url = "https://drive.google.com/file/d/abc/view"
    db.commit()
    db.refresh(o)
    assert (o.seguimientos, o.fecha_ultima_respuesta.isoformat(),
            o.documento_url.endswith("/view")) == (6, "2026-06-26", True)


def test_sin_respuesta_es_nulo(db):
    """NULL significa que el cliente nunca respondio — es la senal, no un hueco."""
    assert _oferta(db).fecha_ultima_respuesta is None


def test_oferta_out_expone_los_tres_campos(db):
    from app.api.v1.comercial import _oferta_out
    o = _oferta(db)
    o.seguimientos = 2
    db.commit()
    salida = _oferta_out(o)
    assert salida["seguimientos"] == 2
    assert "fecha_ultima_respuesta" in salida
    assert "documento_url" in salida


def test_registrar_seguimiento_suma_uno(db):
    from app.api.v1.comercial import registrar_seguimiento
    o = _oferta(db)
    o.seguimientos = 2
    db.commit()
    assert registrar_seguimiento(o.id, db=db, current=ADMIN)["seguimientos"] == 3


def test_registrar_seguimiento_no_toca_la_fecha_de_la_oferta(db):
    """El toque de hoy no es el primer envio: fecha_oferta no se inventa."""
    from app.api.v1.comercial import registrar_seguimiento
    o = _oferta(db)
    registrar_seguimiento(o.id, db=db, current=ADMIN)
    db.refresh(o)
    assert o.fecha_oferta is None


def test_registrar_seguimiento_en_oferta_inexistente_da_404(db):
    from fastapi import HTTPException
    from app.api.v1.comercial import registrar_seguimiento
    with pytest.raises(HTTPException) as e:
        registrar_seguimiento(999999, db=db, current=ADMIN)
    assert e.value.status_code == 404
