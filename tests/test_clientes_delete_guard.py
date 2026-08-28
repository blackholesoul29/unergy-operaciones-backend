"""delete_cliente(): antes de esto, el único mensaje posible ante un 409
asumia siempre "es inversionista de uno o mas proyectos" -- incorrecto
cuando en realidad lo bloqueaba una Oportunidad. Auditoria de Clientes
2026-08-28.

Tambien se descubrio un tercer bloqueador que nadie tenia en cuenta:
email_envios.cliente_id (tabla de solo registro, sin modelo ORM, creada
por SQL crudo) tenia FK en NO ACTION -- borrar un cliente con historial
de correos (41/868 filas reales en produccion) reventaba con un
IntegrityError sin capturar. Se corrigio a ON DELETE SET NULL (migracion
120): un log no deberia bloquear el borrado de nada.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.comercial import Oportunidad
from app.api.v1 import clientes as api

ADMIN = None


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _cliente(db, id=1):
    c = Cliente(id=id, razon_social_nombre="Test")
    db.add(c)
    db.commit()
    return c


def test_sin_ningun_vinculo_se_puede_borrar(db):
    _cliente(db)
    api.delete_cliente(1, db=db, _=ADMIN)
    assert db.get(Cliente, 1) is None


def test_inversionista_bloquea_con_mensaje_correcto(db):
    _cliente(db)
    p = Proyecto(id=10, nombre_comercial="Test")
    db.add(p)
    db.flush()
    db.add(ProyectoInversionista(proyecto_id=10, cliente_id=1))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.delete_cliente(1, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    assert "inversionista" in exc.value.detail
    assert db.get(Cliente, 1) is not None


def test_oportunidad_bloquea_con_mensaje_correcto_no_dice_inversionista(db):
    """Antes del fix, este caso mostraba el mismo mensaje que el de
    inversionista -- incorrecto, no hay ninguna participación real."""
    _cliente(db)
    db.add(Oportunidad(cliente_id=1))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.delete_cliente(1, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    assert "oportunidad" in exc.value.detail.lower()
    assert "inversionista" not in exc.value.detail
    assert db.get(Cliente, 1) is not None
