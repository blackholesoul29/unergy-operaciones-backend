"""Crear un proyecto desde el CRM tiene que producir un Proyecto DE VERDAD, y
tiene que quedar pegado a la oferta.

Los dos agujeros que cubren estos tests son la razon de que
`GET /comercial/proyectos-operando` devuelva nodos con `"proyectos": []`:

1. `ProyectoDesdeCRMIn` solo aceptaba 5 campos (nombre, kWp, depto, municipio,
   operador). Todo lo demas que tiene un proyecto en /proyectos -- coordenadas,
   tipo, estado, clasificacion regulatoria, comunidad energetica, codigos -- se
   descartaba en silencio, asi que la planta nacia vacia.

2. `add_proyecto` colgaba el proyecto de la OPORTUNIDAD (`Proyecto.oportunidad_id`,
   columna eliminada en la auditoria de Proyectos 2026-08-28) y nunca de la
   OFERTA. Pero la API lee las plantas de la M2M `oportunidad_oferta_proyectos`
   (o del `proyecto_id` de la oferta): crear la planta desde el CRM la dejaba
   invisible para la integracion.
"""
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import (
    Portafolio, Proyecto, ProyectoInfoTecnica, ProyectoInversor,
)
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.generacion import GeneracionDiaria
from app.models.contratos import PPAContrato, PPATarifa, ContratoServicio
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
)
from app.api.v1 import comercial as api
from app.schemas.comercial import ProyectoDesdeCRMIn, RegistroComercialIn


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
        # Las precarga _opciones_proyecto() al armar la ficha de cada planta:
        # sin la tabla, la consulta revienta con "no such table".
        Portafolio.__table__, ProyectoInfoTecnica.__table__,
        ProyectoInversor.__table__,
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


@pytest.fixture
def operador(db):
    o = OperadorRed(nombre_legal="AFINIA S.A. E.S.P.", nombre_comercial="AFINIA")
    db.add(o)
    db.commit()
    return o


@pytest.fixture
def negocio(db):
    """Un cliente con una oferta de compra de energia, como OP.COM No.0021-1-2026."""
    return api.registrar(RegistroComercialIn(
        cliente_nuevo={"razon_social_nombre": "PELLETCO S.A.S.",
                       "contactos": [{"email": "compras@pelletco.co"}]},
        ofertas=[{"tipo": "compra_energia", "planta_nombre": "La Catedral",
                  "estado": "oferta"}],
    ), db=db, current=ADMIN)


# -- 1. El proyecto creado desde el CRM es un proyecto completo ---------------

def test_crear_proyecto_desde_crm_guarda_todos_los_campos(db, operador, negocio):
    """Los campos que tiene un proyecto en /proyectos tienen que llegar enteros.

    Antes se descartaban en silencio: el CRM creaba plantas con nombre, kWp,
    departamento, municipio y operador, y nada mas.
    """
    p = api.add_proyecto(
        negocio["id"],
        ProyectoDesdeCRMIn(
            nombre_comercial="La Catedral",
            operador_red_id=operador.id,
            potencia_instalada_kwp=1980.0,
            departamento="Cordoba",
            municipio="Monteria",
            direccion_vereda="Vereda El Cerrito",
            latitud=8.748,
            longitud=-75.881,
            tipo_proyecto="minigranja",
            tipo_tecnologia="solar",
            clasificacion_regulatoria="AGGE",
            estado="en_desarrollo",
            sub_project="catedral",
            codigo_tsf="COLCEST58P2",
            es_comunidad_energetica=True,
            nombre_comunidad="Comunidad Monteria Norte",
        ),
        forzar=False, oferta_id=None, db=db, current=ADMIN,
    )

    guardado = db.query(Proyecto).filter(Proyecto.id == p["id"]).first()
    assert float(guardado.latitud) == pytest.approx(8.748)
    assert float(guardado.longitud) == pytest.approx(-75.881)
    assert guardado.direccion_vereda == "Vereda El Cerrito"
    assert guardado.tipo_proyecto == "minigranja"
    assert guardado.tipo_tecnologia == "solar"
    assert guardado.clasificacion_regulatoria == "AGGE"
    assert guardado.sub_project == "catedral"
    assert guardado.codigo_tsf == "COLCEST58P2"
    # El punto 4: comunidad energetica se puede marcar desde el CRM.
    assert guardado.es_comunidad_energetica is True
    assert guardado.nombre_comunidad == "Comunidad Monteria Norte"
    # Y sigue valiendo lo que ya hacia.
    assert guardado.operador_red_id == operador.id
    assert guardado.operador_red_legal == "AFINIA S.A. E.S.P."


def test_operador_de_red_sigue_siendo_obligatorio(db, negocio):
    """La regla del CRM no se pierde al ampliar el esquema."""
    with pytest.raises(Exception):
        ProyectoDesdeCRMIn(nombre_comercial="Sin operador")


# -- 2. El proyecto creado queda pegado a la OFERTA ---------------------------

def test_crear_proyecto_desde_una_oferta_lo_vincula_a_esa_oferta(db, operador, negocio):
    """Sin esto, /comercial/proyectos-operando sigue devolviendo `proyectos: []`.

    La API lee las plantas de la M2M de la OFERTA. Colgar el proyecto de la
    oportunidad no la alimenta.
    """
    oferta_id = negocio["ofertas"][0]["id"]

    p = api.add_proyecto(
        negocio["id"],
        ProyectoDesdeCRMIn(nombre_comercial="La Catedral", operador_red_id=operador.id,
                           municipio="Monteria", departamento="Cordoba",
                           latitud=8.748, longitud=-75.881),
        forzar=False, oferta_id=oferta_id, db=db, current=ADMIN,
    )

    oferta = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    assert oferta.proyecto_id == p["id"], "la oferta quedo sin planta"

    nodos = api.list_ppas_del_pipeline(
        estado_pipeline=None, todas_las_etapas=False, q=None, db=db, _=ADMIN)
    plantas = [pr for n in nodos["ppas"] for pr in n["proyectos"]]
    assert len(plantas) == 1, "la planta no llego a la API de integracion"
    assert plantas[0]["nombre"] == "La Catedral"
    # Y con la ficha que el punto 6 pedia: operador de red, departamento,
    # coordenadas. Salen del Proyecto, y por eso hacia falta que el CRM los
    # guardara ahi.
    ubicacion = plantas[0]["detalles"]["ubicacion"]
    assert ubicacion["municipio"] == "Monteria"
    assert ubicacion["departamento"] == "Cordoba"
    assert ubicacion["latitud"] == pytest.approx(8.748)
    assert ubicacion["longitud"] == pytest.approx(-75.881)
    assert plantas[0]["detalles"]["operador_red"] == "AFINIA S.A. E.S.P."


def test_acepta_el_payload_literal_del_formulario_de_proyectos(db, operador, negocio):
    """El CRM manda el MISMO formulario de /proyectos (ProyectoForm.vue).

    Este es el punto de union entre los dos repos y no lo cubre ningun otro
    test: si el esquema del backend dejara de aceptar una de estas claves, el
    formulario respondaria 422 y no habria forma de crear la planta. El payload
    esta copiado de `submit()` de ProyectoForm.vue, con sus rarezas: las curvas
    P50/P90 viajan como STRING JSON y las fechas pueden venir en null.
    """
    payload = {
        "nombre_comercial": "GD Taurus IX",
        "estado": "en_desarrollo",
        "tipo_proyecto": "gd",
        "tipo_tecnologia": "solar",
        "departamento": "Cordoba",
        "municipio": "Planeta Rica",
        "direccion_vereda": "Km 4 via Planeta Rica",
        "latitud": 8.41,
        "longitud": -75.58,
        "operador_red_id": operador.id,
        "clasificacion_regulatoria": "GD",
        "sub_project": "taurus9",
        "codigo_tsf": "COLTAU09",
        # serializeMonthArray() manda un string JSON, no una lista.
        "p90_mensual_kwh": "[100,110,120,130,140,150,160,150,140,130,120,110]",
        "p50_mensual_kwh": "[120,130,140,150,160,170,180,170,160,150,140,130]",
        # formatFecha(null) devuelve null, y el submit las manda siempre.
        "fecha_entrada_operacion": None,
        "fecha_fin_representacion": None,
        "potencia_instalada_kwp": 1200.5,
        "es_comunidad_energetica": False,
        "nombre_comunidad": None,
    }

    p = api.add_proyecto(negocio["id"], ProyectoDesdeCRMIn(**payload),
                         forzar=False, oferta_id=negocio["ofertas"][0]["id"],
                         db=db, current=ADMIN)

    guardado = db.query(Proyecto).filter(Proyecto.id == p["id"]).first()
    assert guardado.codigo_tsf == "COLTAU09"
    # El validador coerce_json_list convierte el string a lista.
    assert guardado.p50_mensual_kwh[0] == 120
    assert float(guardado.potencia_instalada_kwp) == pytest.approx(1200.5)


def test_vincular_no_pisa_las_plantas_que_la_oferta_ya_tenia(db, operador, negocio):
    """Una oferta puede cubrir varias plantas (Balmora 1 y 2): crear la segunda
    desde el CRM se SUMA, no reemplaza a la primera."""
    oferta_id = negocio["ofertas"][0]["id"]
    api.add_proyecto(
        negocio["id"],
        ProyectoDesdeCRMIn(nombre_comercial="Balmora 1", operador_red_id=operador.id),
        forzar=False, oferta_id=oferta_id, db=db, current=ADMIN)
    api.add_proyecto(
        negocio["id"],
        ProyectoDesdeCRMIn(nombre_comercial="Balmora 2", operador_red_id=operador.id),
        forzar=True, oferta_id=oferta_id, db=db, current=ADMIN)

    nodos = api.list_ppas_del_pipeline(
        estado_pipeline=None, todas_las_etapas=False, q=None, db=db, _=ADMIN)
    nombres = sorted(pr["nombre"] for n in nodos["ppas"] for pr in n["proyectos"])
    assert nombres == ["Balmora 1", "Balmora 2"]
