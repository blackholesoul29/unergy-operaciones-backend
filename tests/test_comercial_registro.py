"""Registro comercial en una transacción + plantas de la oferta + alerta por oferta.

Lo que se protege acá es el agujero que tenía el registro: se creaba la
oportunidad en una llamada y las ofertas en otra, así que cuando la segunda
fallaba quedaba una oportunidad sin ofertas — INVISIBLE en toda la aplicación,
porque el tablero y la tabla se alimentan de `/comercial/ofertas`. Quien
registraba veía "creado" y después no encontraba nada.
"""
import datetime as dt
import types

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.generacion import GeneracionDiaria
from app.models.contratos import PPAContrato, PPATarifa, ContratoServicio
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
)
from app.api.v1 import comercial as api
from app.schemas.comercial import (
    GestionCreate, OfertaCreate, OfertaUpdate, RegistroComercialIn,
)


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
        Cliente.__table__, ClienteDocumentoComercial.__table__, Contacto.__table__,
        Proyecto.__table__, Frontera.__table__, OperadorRed.__table__,
        GeneracionDiaria.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
        Base.metadata.tables["oportunidad_oferta_proyectos"],
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _ofertas(db):
    return api.list_ofertas_todas(tipo=None, estado=None, resultado=None, q=None,
                                  solo_alerta=False, db=db, current=ADMIN)


def _proyecto(db, nombre):
    p = Proyecto(nombre_comercial=nombre)
    db.add(p)
    db.flush()
    return p


# ── El registro completo, en una sola transacción ────────────────────────────

def test_registrar_cliente_nuevo_deja_las_ofertas_visibles(db):
    """El caso que rompía: registrar y no encontrar nada después."""
    res = api.registrar(RegistroComercialIn(
        cliente_nuevo={"razon_social_nombre": "PELLETCO S.A.S.",
                       "contactos": [{"email": "compras@pelletco.co"}]},
        ofertas=[
            {"tipo": "compra_energia", "planta_nombre": "Catedral", "estado": "oferta",
             "fecha_oferta": dt.date(2026, 8, 3)},
            {"tipo": "servicios_operacionales", "planta_nombre": "Catedral"},
        ]), db=db, current=ADMIN)

    assert len(res["ofertas"]) == 2
    # Y aparecen en la fuente de la vista principal, que es el punto.
    filas = _ofertas(db)
    assert len(filas) == 2
    assert {f["cliente_razon_social"] for f in filas} == {"PELLETCO S.A.S."}
    # La etapa enviada se respeta: antes el front la descartaba y todo nacía en
    # 'oportunidad'.
    assert {f["estado"] for f in filas} == {"oferta", "oportunidad"}
    # El código de seguimiento se autogenera por tipo (COM / REP).
    codigos = {f["codigo_seguimiento"][:6] for f in filas}
    assert codigos == {"OP.COM", "OP.REP"}


def test_registrar_crea_el_contacto_del_cliente_nuevo(db):
    api.registrar(RegistroComercialIn(
        cliente_nuevo={"razon_social_nombre": "ACME S.A.S.",
                       "contactos": [{"email": "juan@acme.co", "nombre": "Juan",
                                      "tipo": "comercial"}]},
        ofertas=[{"tipo": "compra_energia"}]), db=db, current=ADMIN)
    contactos = db.query(Contacto).all()
    assert [c.email for c in contactos] == ["juan@acme.co"]


def test_registrar_sin_ofertas_se_rechaza_en_el_schema():
    """Una oportunidad sin ofertas no se ve en ninguna vista: no se permite."""
    with pytest.raises(ValueError):
        RegistroComercialIn(cliente_id=1, ofertas=[])


def test_registrar_no_deja_nada_a_medias_si_una_oferta_es_invalida(db):
    """Todo o nada: la planta inexistente aborta el registro completo."""
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    with pytest.raises(HTTPException) as e:
        api.registrar(RegistroComercialIn(
            cliente_id=cli.id,
            ofertas=[{"tipo": "compra_energia", "planta_nombre": "Buena"},
                     {"tipo": "compra_energia", "proyecto_ids": [99999]}]),
            db=db, current=ADMIN)
    assert e.value.status_code == 422
    db.rollback()
    assert db.query(Oportunidad).count() == 0
    assert db.query(OportunidadOferta).count() == 0


def test_registrar_avisa_del_cliente_duplicado_con_el_candidato(db):
    """El 409 trae candidato_id para que la UI ofrezca 'usar ese cliente'."""
    db.add(Cliente(razon_social_nombre="PELLETCO SAS"))
    db.commit()
    with pytest.raises(HTTPException) as e:
        api.registrar(RegistroComercialIn(
            cliente_nuevo={"razon_social_nombre": "PELLETCO S.A.S.",
                           "contactos": [{"email": "a@b.co"}]},
            ofertas=[{"tipo": "compra_energia"}]), db=db, current=ADMIN)
    assert e.value.status_code == 409
    assert e.value.detail["candidato_id"] is not None
    db.rollback()

    # Con forzar, entra igual.
    res = api.registrar(RegistroComercialIn(
        cliente_nuevo={"razon_social_nombre": "PELLETCO S.A.S.",
                       "contactos": [{"email": "a@b.co"}]},
        forzar_cliente_duplicado=True,
        ofertas=[{"tipo": "compra_energia"}]), db=db, current=ADMIN)
    assert len(res["ofertas"]) == 1


# ── Plantas de la oferta (M2M) ───────────────────────────────────────────────

def test_las_plantas_de_la_oferta_viajan_en_la_respuesta(db):
    """Balmora 1 y 2: una oferta, dos plantas. Antes había que elegir una."""
    cli = Cliente(razon_social_nombre="BALMORA S.A.S.")
    db.add(cli)
    db.flush()
    b1, b2 = _proyecto(db, "Balmora 1"), _proyecto(db, "Balmora 2")
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id,
        ofertas=[{"tipo": "compra_energia", "planta_nombre": "Balmora 1 y 2",
                  "proyecto_ids": [b1.id, b2.id]}]), db=db, current=ADMIN)

    oferta = res["ofertas"][0]
    assert sorted(p["nombre_comercial"] for p in oferta["plantas"]) == ["Balmora 1", "Balmora 2"]
    # `proyecto_id` queda en la primera: es lo que siguen leyendo el vinculador y
    # la API de integración, y desincronizarlo mostraría una planta en el drawer
    # y otra afuera.
    assert oferta["proyecto_id"] == b1.id


def test_una_oferta_sin_M2M_cae_a_su_proyecto_id(db):
    """Mismo criterio que /firmar: si no hay filas en la M2M vale el id único."""
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    p = _proyecto(db, "Marimonda")
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id,
        ofertas=[{"tipo": "compra_energia", "proyecto_id": p.id}]), db=db, current=ADMIN)
    assert [x["nombre_comercial"] for x in res["ofertas"][0]["plantas"]] == ["Marimonda"]


def test_patch_reescribe_las_plantas_y_la_lista_vacia_desvincula(db):
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    a, b = _proyecto(db, "Uno"), _proyecto(db, "Dos")
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id,
        ofertas=[{"tipo": "compra_energia", "proyecto_ids": [a.id]}]), db=db, current=ADMIN)
    oid = res["ofertas"][0]["id"]

    out = api.update_oferta(oid, OfertaUpdate(proyecto_ids=[b.id]), db=db, current=ADMIN)
    assert [p["nombre_comercial"] for p in out["plantas"]] == ["Dos"]
    assert out["proyecto_id"] == b.id

    out = api.update_oferta(oid, OfertaUpdate(proyecto_ids=[]), db=db, current=ADMIN)
    assert out["plantas"] == []
    assert out["proyecto_id"] is None


def test_patch_devuelve_la_fila_completa_no_un_ok(db):
    """El autosave del drawer necesita la ficha recalculada, no {"ok": true}."""
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id, ofertas=[{"tipo": "compra_energia"}]), db=db, current=ADMIN)
    out = api.update_oferta(res["ofertas"][0]["id"],
                            OfertaUpdate(municipio="Sincelejo", departamento="Sucre"),
                            db=db, current=ADMIN)
    assert out["ficha"]["municipio"] == "Sincelejo"
    assert out["ficha"]["fuentes"]["municipio"] == "oferta"


# ── Campos de seguimiento que antes no se podían escribir ────────────────────

def test_se_puede_registrar_que_el_cliente_respondio(db):
    """Sin esto la señal 'enviada y nunca contestó' no se podía apagar nunca."""
    cli = Cliente(razon_social_nombre="ACME S.A.S.")
    db.add(cli)
    db.flush()
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id,
        ofertas=[{"tipo": "compra_energia", "estado": "oferta",
                  "fecha_oferta": dt.date(2026, 7, 1)}]), db=db, current=ADMIN)
    oid = res["ofertas"][0]["id"]
    assert res["ofertas"][0]["fecha_ultima_respuesta"] is None

    out = api.update_oferta(oid, OfertaUpdate(
        fecha_ultima_respuesta=dt.date(2026, 8, 18),
        fecha_fin_tentativa=dt.date(2032, 12, 31),
        documento_url="https://drive.google.com/file/d/1abc"), db=db, current=ADMIN)
    assert out["fecha_ultima_respuesta"] == dt.date(2026, 8, 18)
    assert out["fecha_fin_tentativa"] == dt.date(2032, 12, 31)
    assert out["documento_url"].endswith("1abc")


# ── La alerta es de la oferta, también cuando se apaga ───────────────────────

def _cliente_con_dos_ofertas_viejas(db):
    """Dos ofertas del mismo cliente, ambas rezagadas hace 40 días."""
    cli = Cliente(razon_social_nombre="TECNI-PLAST S.A.S.")
    db.add(cli)
    db.flush()
    res = api.registrar(RegistroComercialIn(
        cliente_id=cli.id,
        ofertas=[{"tipo": "compra_energia", "planta_nombre": "Margaritas 1", "estado": "oferta"},
                 {"tipo": "compra_energia", "planta_nombre": "Margaritas 2", "estado": "oferta"}]),
        db=db, current=ADMIN)
    viejo = api.col_now() - dt.timedelta(days=40)
    for o in db.query(OportunidadOferta).all():
        o.estado_desde = viejo
    db.commit()
    return res["ofertas"][0], res["ofertas"][1]


def test_una_gestion_de_una_oferta_no_apaga_la_alerta_de_su_hermana(db):
    """El bug: llamar por Margaritas 1 dejaba de avisar que Margaritas 2 seguía
    muda, porque la bitácora era del cliente y no de la oferta."""
    m1, m2 = _cliente_con_dos_ofertas_viejas(db)
    api.add_gestion(m1["oportunidad_id"], GestionCreate(
        tipo="llamada", descripcion="Hablé por Margaritas 1", oferta_id=m1["id"]),
        db=db, current=ADMIN)

    por_id = {f["id"]: f for f in _ofertas(db)}
    assert por_id[m1["id"]]["alerta"] is False
    assert por_id[m2["id"]]["alerta"] is True


def test_una_gestion_del_cliente_sigue_apagando_todas(db):
    """Compatibilidad: `oferta_id` NULL es el comportamiento viejo, y es el que
    conservan las filas que ya estaban en la tabla."""
    m1, m2 = _cliente_con_dos_ofertas_viejas(db)
    api.add_gestion(m1["oportunidad_id"], GestionCreate(
        tipo="reunion", descripcion="Reunión general del contrato marco"),
        db=db, current=ADMIN)
    filas = _ofertas(db)
    assert [f["alerta"] for f in filas] == [False, False]


def test_una_gestion_no_se_puede_colgar_en_la_oferta_de_otro_cliente(db):
    m1, _ = _cliente_con_dos_ofertas_viejas(db)
    otro = Cliente(razon_social_nombre="OTRO S.A.S.")
    db.add(otro)
    db.flush()
    ajena = api.registrar(RegistroComercialIn(
        cliente_id=otro.id, ofertas=[{"tipo": "compra_energia"}]),
        db=db, current=ADMIN)["ofertas"][0]
    with pytest.raises(HTTPException) as e:
        api.add_gestion(m1["oportunidad_id"], GestionCreate(
            tipo="nota", descripcion="no va acá", oferta_id=ajena["id"]),
            db=db, current=ADMIN)
    assert e.value.status_code == 422
