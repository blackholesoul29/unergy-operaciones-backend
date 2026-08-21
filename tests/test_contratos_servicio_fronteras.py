"""Vínculo muchos-a-muchos contrato de servicio ↔ fronteras. Harness sqlite; se
invocan las funciones del router directamente (auth está stubeado en conftest)."""
import types
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
from app.models.contratos import ContratoServicio
from app.models.contrato_frontera import ContratoFrontera
from app.models.fronteras import Frontera
from app.api.v1 import contratos_servicio as api
from app.schemas.contratos_servicio import ContratoServicioCreate, ContratoServicioUpdate

from fastapi import HTTPException


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Cliente.__table__, Proyecto.__table__, ContratoServicio.__table__,
        Frontera.__table__, ContratoFrontera.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _frontera(db, nombre, codigo):
    f = Frontera(nombre_frontera=nombre, codigo_frontera=codigo, tipo_frontera="generacion")
    db.add(f)
    db.flush()
    return f


def _vinculos(db, contrato_id):
    return {
        cf.frontera_id
        for cf in db.query(ContratoFrontera).filter(
            ContratoFrontera.contrato_servicio_id == contrato_id
        ).all()
    }


def test_crear_contrato_con_fronteras(db):
    f1 = _frontera(db, "Planta 1", "FRT001")
    f2 = _frontera(db, "Planta 2", "FRT002")

    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[f1.id, f2.id]),
        db=db, _=ADMIN,
    )

    assert _vinculos(db, contrato.id) == {f1.id, f2.id}
    assert {f.codigo_frontera for f in contrato.fronteras} == {"FRT001", "FRT002"}


def test_actualizar_fronteras_reemplaza_vinculos(db):
    f1 = _frontera(db, "Planta 1", "FRT001")
    f2 = _frontera(db, "Planta 2", "FRT002")
    f3 = _frontera(db, "Planta 3", "FRT003")

    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[f1.id, f2.id]),
        db=db, _=ADMIN,
    )

    # f1 se queda, f2 sale, f3 entra
    actualizado = api.update_contrato(
        contrato.id, ContratoServicioUpdate(frontera_ids=[f1.id, f3.id]), db=db, _=ADMIN,
    )

    assert _vinculos(db, contrato.id) == {f1.id, f3.id}
    assert {f.id for f in actualizado.fronteras} == {f1.id, f3.id}

    # Sin frontera_ids en el payload no se tocan las fronteras actuales
    api.update_contrato(contrato.id, ContratoServicioUpdate(numero_contrato="C-9"), db=db, _=ADMIN)
    assert _vinculos(db, contrato.id) == {f1.id, f3.id}

    # Lista vacía sí desvincula todas
    api.update_contrato(contrato.id, ContratoServicioUpdate(frontera_ids=[]), db=db, _=ADMIN)
    assert _vinculos(db, contrato.id) == set()


def test_get_contrato_devuelve_fronteras(db):
    f1 = _frontera(db, "Planta 1", "FRT001")
    creado = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="representacion", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )

    contrato = api.get_contrato(creado.id, db=db, _=ADMIN)
    assert [(f.id, f.nombre_frontera) for f in contrato.fronteras] == [(f1.id, "Planta 1")]


def test_ids_repetidos_no_duplican_vinculo(db):
    f1 = _frontera(db, "Planta 1", "FRT001")
    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[f1.id, f1.id]),
        db=db, _=ADMIN,
    )
    assert len(contrato.fronteras) == 1
    assert _vinculos(db, contrato.id) == {f1.id}


def test_frontera_inexistente_rechazada(db):
    with pytest.raises(HTTPException) as exc:
        api.create_contrato(
            ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[999]),
            db=db, _=ADMIN,
        )
    assert exc.value.status_code == 400
    # Las fronteras se validan ANTES de insertar: el contrato rechazado no llegó a la BD
    assert db.query(ContratoServicio).count() == 0


def test_frontera_retirada_rechazada_al_vincular(db):
    """No se puede vincular una frontera ya retirada."""
    retirada = _frontera(db, "Planta retirada", "FRT002")
    retirada.deleted_at = datetime.now(timezone.utc)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.create_contrato(
            ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[retirada.id]),
            db=db, _=ADMIN,
        )
    assert exc.value.status_code == 400
    assert db.query(ContratoServicio).count() == 0


def test_frontera_retirada_no_se_lista_y_el_roundtrip_get_patch_funciona(db):
    """Una frontera retirada (soft-delete) no puede aparecer en el GET: el PATCH
    rechaza las retiradas, así que listarlas hace que la API rechace su propia
    salida cuando el frontend devuelve el contrato tal cual lo leyó."""
    viva = _frontera(db, "Planta viva", "FRT001")
    retirada = _frontera(db, "Planta retirada", "FRT002")
    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[viva.id, retirada.id]),
        db=db, _=ADMIN,
    )

    # DELETE /fronteras/{id} solo marca deleted_at; el vínculo sigue en la tabla
    retirada.deleted_at = datetime.now(timezone.utc)
    db.commit()

    leido = api.get_contrato(contrato.id, db=db, _=ADMIN)
    assert {f.id for f in leido.fronteras} == {viva.id}

    # El PATCH acepta de vuelta exactamente lo que el GET entregó
    actualizado = api.update_contrato(
        contrato.id,
        ContratoServicioUpdate(frontera_ids=[f.id for f in leido.fronteras]),
        db=db, _=ADMIN,
    )
    assert {f.id for f in actualizado.fronteras} == {viva.id}

    # ...y ese roundtrip NO borra el vínculo con la frontera retirada: si la
    # frontera se restaura, el contrato vuelve a cubrirla.
    assert _vinculos(db, contrato.id) == {viva.id, retirada.id}
    retirada.deleted_at = None
    db.commit()
    db.expire_all()
    assert {f.id for f in api.get_contrato(contrato.id, db=db, _=ADMIN).fronteras} == {
        viva.id, retirada.id,
    }


def test_constraint_unico_rechaza_duplicados(db):
    f1 = _frontera(db, "Planta 1", "FRT001")
    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="operacion", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )

    db.add(ContratoFrontera(contrato_servicio_id=contrato.id, frontera_id=f1.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
