"""_sync_partes() ahora resuelve contratante_id/prestador_id a partir del
nombre/NIT de texto libre del wizard, no solo al reves (auditoria de
Clientes 2026-08-27). Antes del fix, 0/162 contratos_servicio en produccion
tenian contratante_id o prestador_id poblado -- el campo del wizard nunca
obliga a elegir del autocomplete.

El backfill manual del mismo dia (una corrida unica, ya retirada) encontro
un caso real de falso positivo por similitud de texto sin solapamiento de
tokens ("BALI ENERGY S.A.S." vs "INENERGY S.A.S."): _resolver_cliente_id
exige token en comun ademas del score del matcher compartido, precisamente
para no repetir ese error de forma automatica en cada guardado.
"""
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.schemas.contratos_servicio import ContratoServicioCreate, ContratoServicioUpdate
from app.api.v1 import contratos_servicio as api

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


def _cliente(db, **kw):
    c = Cliente(**kw)
    db.add(c)
    db.flush()
    return c


def test_crear_contrato_resuelve_contratante_id_por_nombre_parecido(db):
    fonsar = _cliente(db, razon_social_nombre="FONSAR S.A.S.")

    out = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="representacion", contratante_nombre="Fonsar SAS"),
        db=db, _=ADMIN,
    )
    assert out.contratante_id == fonsar.id
    # _sync_partes tambien normaliza el nombre al de la ficha canonica del cliente.
    assert out.contratante_nombre == "FONSAR S.A.S."


def test_crear_contrato_resuelve_por_nit_exacto_aunque_el_nombre_difiera(db):
    cliente = _cliente(db, razon_social_nombre="Unergy Energia Digital S.A.S E.S.P",
                       nit_cedula="901.497.656-2")

    out = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="cgm",
                               prestador_nombre="UNERGY ENERGIA DIGITAL SAS ESP",
                               prestador_nit="901497656-2"),
        db=db, _=ADMIN,
    )
    assert out.prestador_id == cliente.id


def test_no_resuelve_sin_solapamiento_real_de_tokens(db):
    """Caso real encontrado en el backfill manual: 'BALI ENERGY S.A.S.' y
    'INENERGY S.A.S.' no comparten ningun token, solo tienen similitud de
    caracteres -- no debe auto-vincularse."""
    _cliente(db, razon_social_nombre="INENERGY S.A.S.")

    out = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="representacion", contratante_nombre="BALI ENERGY S.A.S."),
        db=db, _=ADMIN,
    )
    assert out.contratante_id is None
    assert out.contratante_nombre == "BALI ENERGY S.A.S."  # se conserva el texto libre


def test_no_resuelve_nombre_de_proyecto_por_error_de_captura(db):
    """Caso real: alguien escribio el nombre de la planta en vez de una
    razon social -- no hay ningun cliente parecido, debe quedar sin ID."""
    _cliente(db, razon_social_nombre="RAYOGAS S.A.S. E.S.P.")

    out = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="mantenimiento", prestador_nombre="Minigranja Solar Baraya"),
        db=db, _=ADMIN,
    )
    assert out.prestador_id is None


def test_editar_no_pisa_un_contratante_id_ya_seteado(db):
    correcto = _cliente(db, razon_social_nombre="Cliente Correcto S.A.S.")
    otro = _cliente(db, razon_social_nombre="Otro Cliente S.A.S.")

    contrato = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="representacion",
                               contratante_id=correcto.id, contratante_nombre="Cliente Correcto S.A.S."),
        db=db, _=ADMIN,
    )
    assert contrato.contratante_id == correcto.id

    # Editar otro campo, sin tocar contratante_id -- no debe re-resolverse
    # ni cambiar aunque el texto libre se pareciera a otro cliente.
    out = api.update_contrato(contrato.id, ContratoServicioUpdate(estado="terminado"), db=db, _=ADMIN)
    assert out.contratante_id == correcto.id
    assert out.contratante_id != otro.id
