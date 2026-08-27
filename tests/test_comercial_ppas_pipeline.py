"""La respuesta PPA-céntrica del pipeline: PPA → PROYECTOS → detalles.

Lo que se protege acá:

  · el árbol arranca en el PPA, no en la planta: un PPA con dos plantas es UN
    nodo con dos proyectos, no dos filas;
  · un PPA todavía no firmado es un BORRADOR y no tiene fila en `ppa_contratos`:
    `ppa.id is None` es la única señal, y es la que decide si aparece en
    /servicios. Nada de estados paralelos que puedan contradecirse;
  · solo contratos de ENERGIA (compra y comunidad energética): los servicios
    (representación/CGM) desembocan en contratos_servicio y no son PPAs;
  · las salidas del pipeline (declinado/terminado) NO generan borrador: un
    negocio caído no es un contrato en preparación;
  · `firmado` sin PPA materializado es una INCONSISTENCIA que se muestra, no se
    rellena con un contrato de campos nulos.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import (
    Portafolio, Proyecto, ProyectoInfoTecnica, ProyectoInversor,
)
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.contratos import PPAContrato, PPATarifa
from app.models.comercial import (
    Oportunidad, OportunidadEstadoHistorial, OportunidadGestion, OportunidadOferta,
)
from app.services.comercial import ppas_del_pipeline


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 8, 18)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        Cliente.__table__, Proyecto.__table__, Frontera.__table__,
        # La ficha de la planta las precarga con selectinload: sin la tabla, cada
        # consulta revienta con "no such table" aunque el test no las use.
        Portafolio.__table__, ProyectoInfoTecnica.__table__,
        ProyectoInversor.__table__,
        OperadorRed.__table__, Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
        Base.metadata.tables["oportunidad_oferta_proyectos"],
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _cliente(db, nombre="INVERSIONES TECNI-PLAST S.A.S."):
    c = Cliente(razon_social_nombre=nombre)
    db.add(c); db.flush()
    return c


def _oportunidad(db, cliente=None):
    op = Oportunidad(cliente_id=(cliente or _cliente(db)).id, estado="oportunidad")
    db.add(op); db.flush()
    return op


def _oferta(db, oportunidad=None, estado="oferta", tipo="compra_energia", **kw):
    of = OportunidadOferta(oportunidad_id=(oportunidad or _oportunidad(db)).id,
                           tipo=tipo, estado=estado, **kw)
    db.add(of); db.flush()
    return of


# ── El borrador ──────────────────────────────────────────────────────────────

def test_una_oferta_de_energia_sin_contrato_es_un_ppa_borrador(db):
    """La oferta ES el PPA hasta que se firme. No hay fila en ppa_contratos, así
    que `id` es None — y por eso no puede aparecer en /servicios."""
    _oferta(db, planta_nombre="GD Balmora", estado="oferta",
            fecha_tentativa_inicio=dt.date(2026, 9, 1),
            energia_promedio_kwh_mes=150000)
    db.commit()

    nodos = ppas_del_pipeline(db, hoy=HOY)

    assert len(nodos) == 1
    ppa = nodos[0]["ppa"]
    assert ppa["id"] is None
    assert ppa["aparece_en_servicios"] is False
    # UN solo estado, el del pipeline. "Borrador" no es un estado aparte: es
    # este estado con `id` en None.
    assert ppa["estado"] == "oferta"


def test_una_oferta_firmada_con_contrato_es_un_ppa_real(db):
    """Al firmar, la fila existe en ppa_contratos: `id` se puebla, deja de ser
    borrador y recién ahí aparece en /servicios."""
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014",
                      nombre_interno="PPA Balmora", tipo_contrato="compra",
                      fecha_inicio=dt.date(2026, 9, 1), fecha_fin=dt.date(2033, 8, 31))
    db.add(ppa); db.flush()
    _oferta(db, planta_nombre="GD Balmora", estado="firmado", ppa_contrato_id=ppa.id)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]["ppa"]

    assert nodo["id"] == ppa.id
    assert nodo["estado"] == "firmado"
    assert nodo["aparece_en_servicios"] is True
    assert nodo["numero_codigo_contrato"] == "UNG-2026-014"


# ── El universo ──────────────────────────────────────────────────────────────

def test_las_ofertas_de_servicios_no_son_ppas(db):
    """Representación y CGM desembocan en contratos_servicio, no en un PPA.
    Meterlas acá obligaría a envolver un contrato que no es de energía en un
    nodo que dice ser un PPA."""
    _oferta(db, planta_nombre="GD Energia", tipo="compra_energia", estado="oferta")
    _oferta(db, planta_nombre="GD Servicios", tipo="servicios_operacionales",
            estado="oferta")
    db.commit()

    nodos = ppas_del_pipeline(db, hoy=HOY)

    assert [n["ppa"]["planta_declarada"] for n in nodos] == ["GD Energia"]


def test_las_salidas_del_pipeline_no_generan_borrador(db):
    """Un negocio declinado o terminado no es un contrato en preparación. Con 12
    ofertas de energía declinadas en producción, incluirlas llenaría la respuesta
    de PPAs que nunca van a existir."""
    _oferta(db, planta_nombre="Viva", estado="oferta")
    _oferta(db, planta_nombre="Se cayó", estado="declinado")
    _oferta(db, planta_nombre="Ya terminó", estado="terminado")
    db.commit()

    nodos = ppas_del_pipeline(db, hoy=HOY)

    assert [n["ppa"]["planta_declarada"] for n in nodos] == ["Viva"]


# ── La inconsistencia: firmado sin contrato ──────────────────────────────────

def test_firmado_sin_ppa_no_se_disfraza_de_borrador(db):
    """En producción hay 2 ofertas de energía firmadas y 5 plantas OPERANDO sin
    PPA en registro. Llamarlas 'borrador' diría que el contrato está en
    preparación, cuando la verdad es que el negocio ya cerró y falta cargarlo.
    Y materializarlo automáticamente metería un contrato de campos nulos en
    Cumplimiento. Así que se marca y se ve."""
    _oferta(db, planta_nombre="Firmada sin cargar", estado="firmado")
    _oferta(db, planta_nombre="Operando sin cargar", estado="operando")
    db.commit()

    estados = {n["ppa"]["planta_declarada"]: n["ppa"] for n in ppas_del_pipeline(db, hoy=HOY)}

    # La inconsistencia no necesita una palabra propia: el negocio dice que
    # cerro y no hay contrato cargado. `estado` + `id is None` lo dicen entero,
    # y sin reusar "firmado" con dos significados distintos en el mismo objeto.
    for nombre, etapa in (("Firmada sin cargar", "firmado"),
                          ("Operando sin cargar", "operando")):
        assert estados[nombre]["estado"] == etapa, nombre
        assert estados[nombre]["id"] is None, nombre
        assert estados[nombre]["aparece_en_servicios"] is False, nombre


def test_antes_de_firmar_el_estado_es_la_etapa_y_el_contrato_no_existe(db):
    """Un PPA en preparacion se reconoce por `id is None` en una etapa previa a
    la firma. No hace falta un segundo estado que lo diga."""
    _oferta(db, planta_nombre="En oferta", estado="oferta")
    _oferta(db, planta_nombre="En negociación", estado="contrato")
    db.commit()

    estados = {n["ppa"]["planta_declarada"]: n["ppa"] for n in ppas_del_pipeline(db, hoy=HOY)}
    assert estados["En oferta"]["estado"] == "oferta"
    assert estados["En negociación"]["estado"] == "contrato"
    for n in estados.values():
        assert n["id"] is None, n["planta_declarada"]
        assert n["aparece_en_servicios"] is False


# ── El nivel PROYECTO y sus detalles ─────────────────────────────────────────

def _proyecto(db, **kw):
    p = Proyecto(**kw)
    db.add(p); db.flush()
    return p


def _enlazar(db, ppa, proyecto):
    db.execute(Base.metadata.tables["ppa_contrato_proyectos"].insert().values(
        contrato_id=ppa.id, proyecto_id=proyecto.id))
    db.flush()


def test_el_ppa_materializado_cuelga_las_plantas_de_su_tabla_de_enlace(db):
    """Para un PPA firmado, las plantas del contrato son las de
    ppa_contrato_proyectos: esa es la verdad contractual, no lo que diga la
    oferta."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", sub_project="catedral",
                     municipio="Corozal", departamento="Sucre",
                     potencia_instalada_kwp=990,
                     gen_mensual_promedio_mwh=178.412, gen_promedio_origen="api",
                     gen_promedio_dias=30)
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra")
    db.add(ppa); db.flush()
    _enlazar(db, ppa, proy)
    _oferta(db, planta_nombre="Catedral", estado="operando", ppa_contrato_id=ppa.id)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]

    assert len(nodo["proyectos"]) == 1
    p = nodo["proyectos"][0]
    assert p["proyecto_id"] == proy.id
    assert p["nombre"] == "GD Catedral"
    assert p["api_id_unergy"] == "catedral"
    assert p["detalles"]["energia_promedio_mensual_mwh"] == 178.412
    assert p["detalles"]["energia_promedio_mensual_kwh"] == 178412.0
    assert p["detalles"]["energia_promedio_origen"] == "medido"


def test_el_borrador_cuelga_la_planta_de_la_oferta(db):
    """Sin contrato todavía, la planta es la que declaró la oferta."""
    proy = _proyecto(db, nombre_comercial="GD Balmora", sub_project="balmora")
    _oferta(db, planta_nombre="Balmora", estado="oferta", proyecto_id=proy.id)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]

    assert [p["proyecto_id"] for p in nodo["proyectos"]] == [proy.id]
    assert nodo["proyectos"][0]["api_id_unergy"] == "balmora"


def test_una_oferta_sin_planta_cargada_da_un_ppa_sin_proyectos(db):
    """74% del pipeline no tiene proyecto vinculado. El nodo existe igual —el
    negocio existe— pero `proyectos` viene vacío y no se inventa nada."""
    _oferta(db, planta_nombre="CAPITAL Y SOLUCIONES S.A.S.", estado="oferta")
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]

    assert nodo["proyectos"] == []
    assert nodo["ppa"]["planta_declarada"] == "CAPITAL Y SOLUCIONES S.A.S."


# ── La ficha de la planta: ubicación, operador, potencia, estado ─────────────
#
# Esta información se perdió al pasar la respuesta de "una fila por planta" al
# árbol PPA → PROYECTOS: el nodo quedó con el nombre y la energía. Es justo lo
# que se usa para cruzar esta API con otra, así que vuelve a `detalles` — y con
# `fuentes`, que dice de dónde salió cada campo.

def _operador(db, nombre="ELECTRIFICADORA DEL CARIBE S.A. E.S.P."):
    o = OperadorRed(nombre_legal=nombre)
    db.add(o); db.flush()
    return o


def _frontera(db, proyecto, operador=None):
    f = Frontera(proyecto_id=proyecto.id, nombre_frontera="FN " + proyecto.nombre_comercial,
                 tipo_frontera="generacion",
                 operador_red_id=(operador.id if operador else None))
    db.add(f); db.flush()
    return f


def test_los_detalles_traen_la_ficha_de_la_planta(db):
    """Ubicación, operador de red, potencia, estado y fechas de la planta. Sin
    esto el nodo solo daba el nombre y la energía."""
    op = _operador(db)
    proy = _proyecto(db, nombre_comercial="GD Catedral", sub_project="catedral",
                     estado="en_operacion", municipio="Corozal", departamento="Sucre",
                     latitud=9.317, longitud=-75.292,
                     direccion_vereda="Vereda Las Peñas, km 3",
                     potencia_instalada_kwp=990, potencia_con_cen_mw=0.9,
                     operador_red_id=op.id,
                     fecha_entrada_operacion=dt.date(2025, 3, 1),
                     fecha_inicio_comercializacion=dt.date(2025, 4, 12))
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra")
    db.add(ppa); db.flush()
    _enlazar(db, ppa, proy)
    _oferta(db, planta_nombre="Catedral", estado="operando", ppa_contrato_id=ppa.id)
    db.commit()

    d = ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]

    assert d["detalles"]["ubicacion"] == {
        "municipio": "Corozal", "departamento": "Sucre",
        "texto": "Corozal, Sucre", "latitud": 9.317, "longitud": -75.292,
        "direccion": "Vereda Las Peñas, km 3", "url_mapa": None,
    }
    assert d["detalles"]["operador_red"] == "ELECTRIFICADORA DEL CARIBE S.A. E.S.P."
    assert d["detalles"]["operador_red_id"] == op.id
    assert d["detalles"]["potencia_instalada_kwp"] == 990.0
    assert d["detalles"]["potencia_con_cen_mw"] == 0.9
    assert d["detalles"]["estado_proyecto"] == "en_operacion"
    assert d["detalles"]["estado_proyecto_label"] == "En operación"
    assert d["detalles"]["fecha_entrada_operacion"] == dt.date(2025, 3, 1)
    assert d["detalles"]["fecha_inicio_comercializacion"] == dt.date(2025, 4, 12)
    assert d["fuentes"]["operador_red"] == "proyecto"
    assert d["fuentes"]["municipio"] == "proyecto"


def test_sin_ubicacion_ni_operador_los_campos_son_null_y_la_fuente_lo_dice(db):
    """Nada cargado no es un error: los campos vienen en null y `fuentes` los
    marca en null también, para que se distinga de "no aplica"."""
    proy = _proyecto(db, nombre_comercial="GD Balmora")
    _oferta(db, planta_nombre="Balmora", estado="oferta", proyecto_id=proy.id)
    db.commit()

    d = ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]

    assert d["detalles"]["operador_red"] is None
    assert d["detalles"]["operador_red_id"] is None
    assert d["detalles"]["ubicacion"]["texto"] is None
    assert d["detalles"]["potencia_instalada_kwp"] is None
    assert d["fuentes"]["operador_red"] is None
    assert d["fuentes"]["municipio"] is None


def test_el_operador_de_la_frontera_viaja_con_el_id_de_la_frontera(db):
    """Cuando la planta no tiene vínculo propio, el operador sale de su frontera
    — y el id tiene que ser el de la frontera, no el `operador_red_id` null del
    proyecto: nombre e id hablando de cosas distintas es peor que un null."""
    op = _operador(db, "AFINIA")
    proy = _proyecto(db, nombre_comercial="GD Marimonda")
    _frontera(db, proy, operador=op)
    _oferta(db, planta_nombre="Marimonda", estado="operando", proyecto_id=proy.id)
    db.commit()

    d = ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]

    assert d["detalles"]["operador_red"] == "AFINIA"
    assert d["detalles"]["operador_red_id"] == op.id
    assert d["fuentes"]["operador_red"] == "frontera"


def test_la_oferta_rellena_la_ubicacion_y_el_operador_que_la_planta_no_tiene(db):
    """La oferta declara ubicación y operador para las plantas que todavía no los
    tienen cargados. Es el último escalón antes del null, y `fuentes` avisa que
    es declarado y no de la planta."""
    op = _operador(db, "CELSIA")
    proy = _proyecto(db, nombre_comercial="GD Taurus IX", departamento="Tolima")
    _oferta(db, planta_nombre="Taurus IX", estado="operando", proyecto_id=proy.id,
            municipio="Espinal", departamento="Huila", operador_red_id=op.id)
    db.commit()

    d = ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]

    assert d["detalles"]["ubicacion"]["municipio"] == "Espinal"
    assert d["fuentes"]["municipio"] == "oferta"
    # El departamento SÍ está en la planta: manda el proyecto y no se pisa con lo
    # declarado. Los dos campos se resuelven por separado a propósito.
    assert d["detalles"]["ubicacion"]["departamento"] == "Tolima"
    assert d["fuentes"]["departamento"] == "proyecto"
    assert d["detalles"]["operador_red"] == "CELSIA"
    assert d["detalles"]["operador_red_id"] == op.id
    assert d["fuentes"]["operador_red"] == "oferta"


def test_lo_declarado_por_la_oferta_no_se_le_atribuye_a_la_planta_hermana(db):
    """El contrato cubre dos plantas y la oferta nombró una. Lo que la oferta
    declara —municipio, operador, energía— es una afirmación sobre ESA planta:
    copiárselo a la hermana le inventaría datos que nadie declaró."""
    op = _operador(db, "ENEL")
    nombrada = _proyecto(db, nombre_comercial="GD Balmora 1")
    hermana = _proyecto(db, nombre_comercial="GD Balmora 2")
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-020", tipo_contrato="compra")
    db.add(ppa); db.flush()
    _enlazar(db, ppa, nombrada)
    _enlazar(db, ppa, hermana)
    _oferta(db, planta_nombre="Balmora 1", estado="operando", ppa_contrato_id=ppa.id,
            proyecto_id=nombrada.id, municipio="Sincelejo", operador_red_id=op.id,
            energia_promedio_kwh_mes=150000)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]
    por_nombre = {p["nombre"]: p for p in nodo["proyectos"]}

    assert por_nombre["GD Balmora 1"]["detalles"]["ubicacion"]["municipio"] == "Sincelejo"
    assert por_nombre["GD Balmora 1"]["detalles"]["operador_red"] == "ENEL"
    assert por_nombre["GD Balmora 1"]["detalles"]["energia_promedio_origen"] == "declarado"

    otra = por_nombre["GD Balmora 2"]["detalles"]
    assert otra["ubicacion"]["municipio"] is None
    assert otra["operador_red"] is None
    assert otra["energia_promedio_mensual_mwh"] is None
    assert otra["energia_promedio_origen"] is None


# ── Las condiciones: tentativas en el borrador, del contrato al firmar ───────

def test_el_borrador_declara_sus_condiciones_como_tentativas(db):
    """La oferta ya trae periodo y energía: es lo que hace posible el borrador.
    `origen` dice que son tentativas y no pactadas — sin eso, una fecha de la
    oferta y una del contrato firmado se leen igual."""
    _oferta(db, planta_nombre="GD Balmora", estado="oferta",
            fecha_tentativa_inicio=dt.date(2026, 9, 1),
            fecha_fin_tentativa=dt.date(2033, 8, 31),
            energia_promedio_kwh_mes=150000)
    db.commit()

    c = ppas_del_pipeline(db, hoy=HOY)[0]["ppa"]["condiciones"]

    assert c["origen"] == "oferta"
    assert c["fecha_inicio"] == dt.date(2026, 9, 1)
    assert c["fecha_fin"] == dt.date(2033, 8, 31)
    assert c["duracion_meses"] == 84
    assert c["energia_kwh_mes"] == 150000.0


def test_al_firmar_las_condiciones_salen_del_contrato_no_de_la_oferta(db):
    """El contrato es la fuente única en cuanto existe. Si la oferta decía otra
    cosa, la oferta quedó vieja: leerla sería mostrar una condición que nadie
    firmó."""
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra",
                      fecha_inicio=dt.date(2026, 10, 1), fecha_fin=dt.date(2032, 9, 30),
                      cantidad_minima_kwh_mes=200000)
    db.add(ppa); db.flush()
    _oferta(db, planta_nombre="GD Balmora", estado="firmado", ppa_contrato_id=ppa.id,
            fecha_tentativa_inicio=dt.date(2026, 9, 1),
            fecha_fin_tentativa=dt.date(2033, 8, 31),
            energia_promedio_kwh_mes=150000)
    db.commit()

    c = ppas_del_pipeline(db, hoy=HOY)[0]["ppa"]["condiciones"]

    assert c["origen"] == "contrato"
    assert c["fecha_inicio"] == dt.date(2026, 10, 1)
    assert c["fecha_fin"] == dt.date(2032, 9, 30)
    assert c["energia_kwh_mes"] == 200000.0


# ── Comunidad energética: una característica del PPA, no otro tipo ───────────

def test_comunidad_energetica_es_una_marca_del_ppa_no_un_arbol_aparte(db):
    """Un PPA de comunidad energética sigue siendo un PPA: entra al mismo árbol
    y se distingue por una marca."""
    _oferta(db, planta_nombre="Comunidad El Prado", tipo="comunidad_energetica",
            estado="oferta")
    _oferta(db, planta_nombre="GD Balmora", tipo="compra_energia", estado="oferta")
    db.commit()

    marcas = {n["ppa"]["planta_declarada"]: n["ppa"]["es_comunidad_energetica"]
              for n in ppas_del_pipeline(db, hoy=HOY)}

    assert marcas == {"Comunidad El Prado": True, "GD Balmora": False}


def test_el_ppa_firmado_lleva_la_marca_en_su_propia_fila(db):
    """Al materializarse, la característica pasa a ser del contrato: si mañana se
    borra la oferta, el PPA sigue sabiendo lo que es."""
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-020", tipo_contrato="compra",
                      es_comunidad_energetica=True)
    db.add(ppa); db.flush()
    _oferta(db, planta_nombre="Comunidad El Prado", tipo="compra_energia",
            estado="firmado", ppa_contrato_id=ppa.id)
    db.commit()

    assert ppas_del_pipeline(db, hoy=HOY)[0]["ppa"]["es_comunidad_energetica"] is True


# ── Plantas asociadas a la oferta (ofertas multi-planta) ─────────────────────

def _asociar(db, oferta, *proyectos):
    for p in proyectos:
        db.execute(Base.metadata.tables["oportunidad_oferta_proyectos"].insert().values(
            oferta_id=oferta.id, proyecto_id=p.id))
    db.flush()


def test_una_oferta_puede_declarar_varias_plantas(db):
    """En producción hay ofertas que nombran dos plantas ("Balmora 1 y 2"). Con un
    solo proyecto_id había que elegir una, y la generación de esa se mostraba como
    si fuera la del contrato entero."""
    uno = _proyecto(db, nombre_comercial="GD Balmora 1", sub_project="balmora1")
    dos = _proyecto(db, nombre_comercial="GD Balmora 2", sub_project="balmora2")
    of = _oferta(db, planta_nombre="Balmora 1 y 2", estado="oferta")
    _asociar(db, of, uno, dos)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]

    assert [p["nombre"] for p in nodo["proyectos"]] == ["GD Balmora 1", "GD Balmora 2"]
    assert nodo["ppa"]["cantidad_proyectos"] == 2


def test_la_oferta_de_una_sola_planta_sigue_funcionando_por_proyecto_id(db):
    """La columna vieja no se rompe: las ofertas ya vinculadas siguen resolviendo
    su planta sin necesidad de backfill."""
    proy = _proyecto(db, nombre_comercial="GD Balmora", sub_project="balmora")
    _oferta(db, planta_nombre="Balmora", estado="oferta", proyecto_id=proy.id)
    db.commit()

    nodo = ppas_del_pipeline(db, hoy=HOY)[0]

    assert [p["nombre"] for p in nodo["proyectos"]] == ["GD Balmora"]
    assert nodo["ppa"]["cantidad_proyectos"] == 1


# ── Materializar: la firma crea el PPA de verdad ─────────────────────────────

@pytest.fixture
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.database import get_db
    from app.api.v1.auth import get_current_user
    from app.api.v1 import comercial as comercial_api

    app = FastAPI()
    app.include_router(comercial_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=1, rol=types.SimpleNamespace(value="admin"))
    return TestClient(app)


FIRMA = {"fecha_inicio": "2026-09-01", "fecha_fin": "2033-08-31", "tarifa_base": 300}


def test_una_oferta_de_comunidad_energetica_se_puede_firmar(db, client):
    """Antes solo compra_energia derivaba en PPA. Comunidad energética también es
    un contrato de energía —solo con otra característica—, así que rechazarla
    dejaba ese negocio sin forma de materializarse."""
    of = _oferta(db, planta_nombre="Comunidad El Prado", tipo="comunidad_energetica",
                 estado="contrato")
    db.commit()

    r = client.post(f"/api/v1/comercial/ofertas/{of.id}/firmar", json=FIRMA)

    assert r.status_code == 201, r.text
    ppa = db.query(PPAContrato).filter(PPAContrato.id == r.json()["ppa_contrato_id"]).one()
    assert ppa.es_comunidad_energetica is True


def test_firmar_una_oferta_de_energia_no_la_marca_como_comunidad(db, client):
    of = _oferta(db, planta_nombre="GD Balmora", tipo="compra_energia", estado="contrato")
    db.commit()

    r = client.post(f"/api/v1/comercial/ofertas/{of.id}/firmar", json=FIRMA)

    assert r.status_code == 201, r.text
    ppa = db.query(PPAContrato).filter(PPAContrato.id == r.json()["ppa_contrato_id"]).one()
    assert ppa.es_comunidad_energetica is False


def test_firmar_una_oferta_multi_planta_pasa_TODAS_sus_plantas_al_contrato(db, client):
    """Si la oferta cubre dos plantas, el PPA firmado tiene que quedar con las dos:
    dejar una afuera haría que Cumplimiento midiera el compromiso del contrato
    contra la generación de media planta."""
    uno = _proyecto(db, nombre_comercial="GD Balmora 1")
    dos = _proyecto(db, nombre_comercial="GD Balmora 2")
    of = _oferta(db, planta_nombre="Balmora 1 y 2", estado="contrato")
    _asociar(db, of, uno, dos)
    db.commit()

    r = client.post(f"/api/v1/comercial/ofertas/{of.id}/firmar", json=FIRMA)

    assert r.status_code == 201, r.text
    ppa = db.query(PPAContrato).filter(PPAContrato.id == r.json()["ppa_contrato_id"]).one()
    assert sorted(p.nombre_comercial for p in ppa.proyectos) == ["GD Balmora 1", "GD Balmora 2"]


# ── La ruta ──────────────────────────────────────────────────────────────────

def test_la_ruta_devuelve_el_arbol_de_ppas_con_sus_conteos(db, client):
    """El sobre trae los conteos por estado ya hechos: quien integra no tiene
    que recorrer la lista para saber en qué está cada negocio.

    Fijate que la planta con contrato está `operando`, no `firmado`: el conteo
    viejo (`por_estado_ppa`) la contaba como "firmado" porque ahí esa palabra
    significaba "existe la fila en ppa_contratos", y perdía que ya está
    entregando energía. Con un solo vocabulario el conteo dice la verdad."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", sub_project="catedral",
                     gen_mensual_promedio_mwh=178.4, gen_promedio_origen="api",
                     gen_promedio_dias=30)
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra",
                      fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    db.add(ppa); db.flush()
    _enlazar(db, ppa, proy)
    _oferta(db, planta_nombre="Catedral", estado="operando", ppa_contrato_id=ppa.id)
    _oferta(db, planta_nombre="GD Balmora", estado="oferta")
    db.commit()

    r = client.get("/api/v1/comercial/proyectos-operando")

    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 2
    assert d["por_estado"] == {"oferta": 1, "operando": 1}
    con_contrato = next(n for n in d["ppas"] if n["ppa"]["id"] is not None)
    assert con_contrato["ppa"]["id"] == ppa.id
    assert con_contrato["ppa"]["estado"] == "operando"
    assert con_contrato["proyectos"][0]["api_id_unergy"] == "catedral"
    assert con_contrato["proyectos"][0]["detalles"]["energia_promedio_origen"] == "medido"


def test_la_ruta_serializa_los_enums_como_slugs(db, client):
    """`estado` y `tipo` son Enum de SQLAlchemy: sin resolverlos, la respuesta
    saldría con el repr del enum en vez del slug."""
    _oferta(db, planta_nombre="GD Balmora", tipo="comunidad_energetica", estado="oferta")
    db.commit()

    ppa = client.get("/api/v1/comercial/proyectos-operando").json()["ppas"][0]["ppa"]

    assert ppa["estado"] == "oferta"
    assert ppa["es_comunidad_energetica"] is True


def test_la_ruta_filtra_por_texto(db, client):
    """Busca en el nombre de la planta, el cliente y el código de seguimiento."""
    _oferta(db, planta_nombre="Bayunca", estado="oferta")
    _oferta(db, planta_nombre="Marimonda", estado="oferta")
    db.commit()

    d = client.get("/api/v1/comercial/proyectos-operando", params={"q": "mari"}).json()

    assert [n["ppa"]["planta_declarada"] for n in d["ppas"]] == ["Marimonda"]
    assert d["total"] == 1


def test_la_ruta_rechaza_una_etapa_que_no_existe(db, client):
    """422 y no 200 con lista vacía: pedir una etapa inventada y recibir cero
    resultados se lee como 'no hay ninguna', que es otra cosa."""
    r = client.get("/api/v1/comercial/proyectos-operando",
                   params={"estado_pipeline": "inventada"})

    assert r.status_code == 422
    assert "inventada" in r.json()["detail"]


def test_la_ruta_no_la_captura_el_path_param_de_oferta(db, client):
    """`/comercial/ofertas/{oferta_id}` está tipado int; si esta ruta quedara
    tapada por otra, esto daría 422 en vez de 200."""
    r = client.get("/api/v1/comercial/proyectos-operando")
    assert r.status_code == 200, r.text


def test_sin_datos_la_ruta_devuelve_un_sobre_vacio_no_un_404(db, client):
    r = client.get("/api/v1/comercial/proyectos-operando")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 0 and d["ppas"] == [] and d["por_estado"] == {}


def test_acotar_la_etapa_no_recorta_el_arbol_de_las_que_quedan(db, client):
    """El filtro elige PPAs, no recorta su contenido: un PPA que entra sigue
    trayendo todas sus plantas."""
    uno = _proyecto(db, nombre_comercial="GD Balmora 1")
    dos = _proyecto(db, nombre_comercial="GD Balmora 2")
    of = _oferta(db, planta_nombre="Balmora 1 y 2", estado="oferta")
    _asociar(db, of, uno, dos)
    _oferta(db, planta_nombre="Otra en firma", estado="firmado")
    db.commit()

    d = client.get("/api/v1/comercial/proyectos-operando",
                   params={"estado_pipeline": "oferta"}).json()

    assert d["total"] == 1
    assert len(d["ppas"][0]["proyectos"]) == 2


# ── El PPA se resuelve por dos caminos, no solo por el enlace de la oferta ────

def test_el_ppa_de_la_planta_cuenta_aunque_la_oferta_no_lo_tenga_enlazado(db):
    """En producción NINGÚN PPA está enlazado a su oferta: los contratos son
    anteriores al CRM. Mirar solo `oferta.ppa_contrato_id` marcaba como
    'sin_contrato' —o sea "falta cargarlo"— a plantas que SÍ tienen contrato. Es
    el mismo doble camino que ya resolvía la vista por planta."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", sub_project="catedral")
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra",
                      fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31),
                      cantidad_minima_kwh_mes=150000)
    db.add(ppa); db.flush()
    _enlazar(db, ppa, proy)
    of = _oferta(db, planta_nombre="Catedral", estado="operando", proyecto_id=proy.id)
    assert of.ppa_contrato_id is None          # no hay enlace desde la oferta
    db.commit()

    n = ppas_del_pipeline(db, hoy=HOY)[0]

    assert n["ppa"]["id"] is not None
    assert n["ppa"]["id"] == ppa.id
    assert n["ppa"]["aparece_en_servicios"] is True
    # y se distingue de dónde salió, que no es lo mismo que un enlace explícito
    assert n["ppa"]["fuente_ppa"] == "proyecto"
    assert n["ppa"]["condiciones"]["origen"] == "contrato"
    assert n["ppa"]["condiciones"]["energia_kwh_mes"] == 150000.0


def test_el_enlace_de_la_oferta_le_gana_al_ppa_del_proyecto(db):
    """Si la oferta declara su contrato, ese manda: es el vínculo explícito."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    viejo = PPAContrato(numero_codigo_contrato="VIEJO", tipo_contrato="compra",
                        fecha_inicio=dt.date(2021, 1, 1), fecha_fin=dt.date(2025, 12, 31))
    nuevo = PPAContrato(numero_codigo_contrato="ENLAZADO", tipo_contrato="compra",
                        fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    db.add_all([viejo, nuevo]); db.flush()
    _enlazar(db, viejo, proy)
    _oferta(db, planta_nombre="Catedral", estado="operando", proyecto_id=proy.id,
            ppa_contrato_id=nuevo.id)
    db.commit()

    n = ppas_del_pipeline(db, hoy=HOY)[0]

    assert n["ppa"]["numero_codigo_contrato"] == "ENLAZADO"
    assert n["ppa"]["fuente_ppa"] == "oferta"


def test_sin_contrato_por_ningun_camino_sigue_siendo_la_inconsistencia(db):
    """La alarma tiene que seguir sonando cuando el contrato de verdad no está."""
    proy = _proyecto(db, nombre_comercial="GD Sin Contrato")
    _oferta(db, planta_nombre="Sin contrato", estado="operando", proyecto_id=proy.id)
    db.commit()

    n = ppas_del_pipeline(db, hoy=HOY)[0]

    assert n["ppa"]["id"] is None
    assert n["ppa"]["fuente_ppa"] is None


# ── Un PPA es UN nodo, aunque lo alimenten varias ofertas ────────────────────

def test_dos_ofertas_del_mismo_contrato_dan_un_solo_nodo(db):
    """El nodo es el PPA. Si dos ofertas desembocan en el mismo contrato y cada
    una generara su nodo, el contrato aparecería dos veces y `total` lo contaría
    doble — que es justo lo que una vista PPA-céntrica no puede hacer."""
    uno = _proyecto(db, nombre_comercial="GD Balmora 1")
    dos = _proyecto(db, nombre_comercial="GD Balmora 2")
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-030", tipo_contrato="compra",
                      fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2032, 12, 31))
    db.add(ppa); db.flush()
    _enlazar(db, ppa, uno); _enlazar(db, ppa, dos)
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, planta_nombre="Balmora 1", estado="operando",
            proyecto_id=uno.id, numero_oferta="OF.COM No.001-2026")
    _oferta(db, oportunidad=op, planta_nombre="Balmora 2", estado="operando",
            proyecto_id=dos.id, numero_oferta="OF.COM No.002-2026")
    db.commit()

    nodos = ppas_del_pipeline(db, hoy=HOY)

    assert len(nodos) == 1
    n = nodos[0]
    assert n["ppa"]["id"] == ppa.id
    # las dos ofertas viajan, cada una con su código
    assert sorted(o["codigo_seguimiento"] for o in n["ppa"]["ofertas"]) == [
        "OP.COM No.001-2026", "OP.COM No.002-2026"]
    # y las plantas del contrato son las dos
    assert [p["nombre"] for p in n["proyectos"]] == ["GD Balmora 1", "GD Balmora 2"]


def test_dos_borradores_distintos_no_se_colapsan(db):
    """Sin contrato no hay nada por lo que agrupar: cada oferta es su propio PPA
    en preparación."""
    _oferta(db, planta_nombre="Balmora", estado="oferta")
    _oferta(db, planta_nombre="Catedral", estado="oferta")
    db.commit()

    assert len(ppas_del_pipeline(db, hoy=HOY)) == 2


# ── La ficha COMPLETA de la planta ───────────────────────────────────────────
#
# Con la ubicación y el operador no alcanzaba: quien integra necesita la planta
# como está creada en la plataforma —con qué id se cruza en cada sistema, cómo
# está clasificada, qué tiene instalado, qué fronteras liquida, qué servicios
# tiene y en qué punto de obra está.
#
# Lo que se protege acá: que los bloques viajen SIEMPRE (una planta sin ficha
# técnica es el caso normal, no un error), que no se cuelen credenciales de
# equipo, y que agregar todo esto no cueste una consulta por planta.

def _info_tecnica(db, proyecto, **kw):
    it = ProyectoInfoTecnica(proyecto_id=proyecto.id, **kw)
    db.add(it); db.flush()
    return it


def _inversor(db, proyecto, **kw):
    inv = ProyectoInversor(proyecto_id=proyecto.id, **kw)
    db.add(inv); db.flush()
    return inv


def _con_contrato(db, proyecto, estado="operando"):
    """La planta colgada de un PPA firmado, que es el nodo que se inspecciona."""
    ppa = PPAContrato(numero_codigo_contrato="UNG-2026-014", tipo_contrato="compra")
    db.add(ppa); db.flush()
    _enlazar(db, ppa, proyecto)
    _oferta(db, planta_nombre=proyecto.nombre_comercial, estado=estado,
            ppa_contrato_id=ppa.id)
    db.commit()
    return ppa


def _detalles(db):
    return ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]["detalles"]


def test_la_ficha_trae_el_identificador_de_cada_sistema(db):
    """`sub_project`, `project_id_solenium` y `sunfactory_project_id` son tres
    espacios de ids distintos: cruzar por el equivocado es el error clásico de
    una integración, así que van los tres con el sistema en la clave."""
    porta = Portafolio(nombre="Portafolio Caribe")
    db.add(porta); db.flush()
    proy = _proyecto(db, nombre_comercial="GD Catedral",
                     sub_project="catedral", codigo_cnd="CND-0912",
                     codigo_tsf="TSF-77", project_id_solenium="SOL-45",
                     sunfactory_project_id=310, origina_code="MF-CAT",
                     quoia_nodo_id=8, quoia_reporte_generacion_id=91,
                     portafolio_id=porta.id)
    _con_contrato(db, proy)

    ident = _detalles(db)["identificacion"]

    assert ident["nombre_comercial"] == "GD Catedral"
    assert ident["sub_project"] == "catedral"
    assert ident["project_id_solenium"] == "SOL-45"
    assert ident["sunfactory_project_id"] == 310
    assert ident["codigo_cnd"] == "CND-0912"
    assert ident["quoia_nodo_id"] == 8
    # El portafolio viaja con nombre y con id: el nombre para leerlo, el id para
    # agrupar sin depender de cómo esté escrito.
    assert ident["portafolio"] == "Portafolio Caribe"
    assert ident["portafolio_id"] == porta.id


def test_la_ficha_trae_la_clasificacion_en_sus_tres_ejes(db):
    """Regulatoria (CREG), interna y tecnología son ejes independientes: no se
    derivan uno del otro y por eso viajan los tres."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", clasificacion_regulatoria="AGGE",
                     tipo_tecnologia="solar", tipo_proyecto="minigranja",
                     es_comunidad_energetica=True, nombre_comunidad="CEN Sucre")
    _con_contrato(db, proy)

    c = _detalles(db)["clasificacion"]

    assert c == {"clasificacion_regulatoria": "AGGE", "tipo_tecnologia": "solar",
                 "tipo_proyecto": "minigranja", "es_comunidad_energetica": True,
                 "nombre_comunidad": "CEN Sucre"}


def test_la_ficha_tecnica_trae_lo_declarado_y_los_equipos_cargados(db):
    """El conteo de la ficha y la lista de inversores son datos distintos y los
    dos viajan: uno es lo que declaró el diseño, el otro lo que está cargado
    (y es lo que se usa para reportar fallas por inversor)."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", tipo_conexion="trifásica",
                     produccion_especifica_kwh_kwp=1450.5)
    # El conteo de paneles vive en la ficha técnica y solo ahí: hasta 2026-08-19
    # estaba duplicado en `proyectos.cantidad_total_paneles`, y esa columna se
    # eliminó.
    _info_tecnica(db, proy, voltaje_red="13.2 kV", potencia_ac_kw=900,
                  capacidad_instalada_kwp=990, tipo_tracker="1E",
                  cantidad_total_paneles=1800,
                  marca_paneles="Trina", potencia_panel_kwp="0.55",
                  cantidad_inversores=5, marca_inversores="Huawei",
                  cantidad_strings=48, marca_transformador="Siemens",
                  tiene_almacenamiento=True, capacidad_almacenamiento_kwh=250)
    _inversor(db, proy, nombre="Inversor 2", potencia_nominal_kw=300, orden=2,
              marca="Huawei", tipo="central")
    _inversor(db, proy, nombre="Inversor 1", potencia_nominal_kw=300, orden=1)
    _inversor(db, proy, nombre="Retirado", potencia_nominal_kw=50, orden=3,
              activo=False)
    _con_contrato(db, proy)

    t = _detalles(db)["tecnica"]

    assert t["voltaje_red"] == "13.2 kV"
    assert t["tipo_conexion"] == "trifásica"
    assert t["potencia_ac_kw"] == 900.0
    assert t["produccion_especifica_kwh_kwp"] == 1450.5
    assert t["paneles"]["cantidad_total"] == 1800
    assert t["paneles"]["marca"] == "Trina"
    assert t["inversores"]["cantidad"] == 5
    assert t["inversores"]["marca"] == "Huawei"
    # En el orden en que están cargados, y sin el que está dado de baja: un
    # inversor retirado no está en la planta y sumaría potencia que no existe.
    assert [i["nombre"] for i in t["inversores"]["equipos"]] == [
        "Inversor 1", "Inversor 2"]
    assert t["inversores"]["equipos"][1]["tipo"] == "central"
    assert t["almacenamiento"] == {"tiene": True, "capacidad_kwh": 250.0,
                                   "marca": None, "modelo": None}
    assert t["equipos_marcas"]["transformador"] == "Siemens"


def test_sin_ficha_tecnica_el_bloque_viaja_igual_todo_en_null(db):
    """`proyecto_info_tecnica` puede no existir —es el caso normal en la mitad
    de las plantas—. Devolver el bloque ausente obligaría a quien integra a
    programar dos formas para la misma cosa."""
    proy = _proyecto(db, nombre_comercial="GD Balmora")
    _con_contrato(db, proy)

    t = _detalles(db)["tecnica"]

    assert t["voltaje_red"] is None
    assert t["potencia_ac_kw"] is None
    assert t["inversores"]["equipos"] == []
    # `tiene` es un booleano, no un null: sin ficha, no hay almacenamiento.
    assert t["almacenamiento"]["tiene"] is False


def test_las_fronteras_traen_su_codigo(db):
    """Las fronteras son con lo que se liquida y no pueden vivir a nivel de PPA:
    una planta tiene generación y consumo, y un contrato de dos plantas tiene
    las de las dos."""
    op = _operador(db)
    proy = _proyecto(db, nombre_comercial="GD Catedral", potencia_instalada_kwp=900)
    db.add_all([
        Frontera(proyecto_id=proy.id, nombre_frontera="FN Catedral GEN",
                 codigo_frontera="Frt00123", tipo_frontera="generacion",
                 estado="activa", nivel_tension_kv=13.2,
                 operador_red_id=op.id),
        Frontera(proyecto_id=proy.id, nombre_frontera="FN Catedral CON",
                 codigo_frontera="Frt00124", tipo_frontera="consumo",
                 estado="activa"),
        Frontera(proyecto_id=proy.id, nombre_frontera="FN Borrada",
                 codigo_frontera="Frt00099", tipo_frontera="generacion",
                 deleted_at=dt.datetime(2026, 1, 1)),
    ])
    db.flush()
    _con_contrato(db, proy)

    fronteras = _detalles(db)["fronteras"]

    # La borrada no está: la relación del modelo no filtra el soft delete, así
    # que una frontera dada de baja saldría como vigente.
    assert [f["codigo_frontera"] for f in fronteras] == ["Frt00123", "Frt00124"]
    gen = fronteras[0]
    assert gen["tipo_frontera"] == "generacion"
    assert gen["nivel_tension_kv"] == 13.2
    # capacidad_transporte_mw/capacidad_efectiva_mw ya no son columnas de
    # Frontera (eliminadas 2026-08-25) -- se repuntan a
    # Proyecto.potencia_instalada_kwp/1000, solo para la de generación.
    assert gen["capacidad_transporte_mw"] == 0.9
    assert gen["capacidad_efectiva_mw"] == 0.9
    assert fronteras[1]["capacidad_transporte_mw"] is None
    assert fronteras[1]["capacidad_efectiva_mw"] is None
    assert gen["operador_red"] == "ELECTRIFICADORA DEL CARIBE S.A. E.S.P."
    assert gen["operador_red_id"] == op.id
    # Sin operador_red_id vinculado, esta frontera no tiene operador -- ya no
    # hay texto libre de respaldo.
    assert fronteras[1]["operador_red"] is None
    assert fronteras[1]["operador_red_id"] is None


def test_los_servicios_activos_viajan_sin_el_prefijo_srv(db):
    """Son los flags del Proyecto —qué servicio está activo—, no los contratos
    que los respaldan, que son otra entidad."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", srv_operacion=True,
                     srv_representacion=True, srv_cgm=True, srv_ppa=True,
                     fecha_fin_representacion=dt.date(2030, 12, 31))
    _con_contrato(db, proy)

    s = _detalles(db)["servicios"]

    assert s["operacion"] is True and s["representacion"] is True
    assert s["cgm"] is True and s["ppa"] is True
    assert s["promotor"] is False and s["rec"] is False
    assert s["fecha_fin_representacion"] == dt.date(2030, 12, 31)


def test_la_construccion_dice_lo_que_el_estado_del_proyecto_no_distingue(db):
    """`estado` se queda en `en_desarrollo` toda la obra y no separa una planta
    en cimientos de una que se energiza la semana entrante."""
    proy = _proyecto(db, nombre_comercial="GD Catedral", estado="en_desarrollo",
                     fase_construccion="proximo_energizar", avance_obra_pct=93.5,
                     fecha_estimada_energizacion=dt.date(2026, 9, 15),
                     origen="tsf_sync")
    _con_contrato(db, proy, estado="firmado")

    c = _detalles(db)["construccion"]

    assert c == {"fase": "proximo_energizar", "avance_obra_pct": 93.5,
                 "fecha_estimada_energizacion": dt.date(2026, 9, 15),
                 "origen_registro": "tsf_sync"}


def test_la_simulacion_lee_el_p50_aunque_este_guardado_como_texto(db):
    """Las filas viejas guardan la serie como texto JSON en vez de array.
    Leerla cruda tumbaba /comercial con un 500, y acá sería el mismo 500."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    _con_contrato(db, proy)
    db.execute(Proyecto.__table__.update()
               .where(Proyecto.__table__.c.id == proy.id)
               .values(p50_mensual_kwh="[100000, 110000, 120000, 130000, 140000, "
                                       "150000, 160000, 150000, 140000, 130000, "
                                       "120000, 110000]"))
    db.commit()

    s = _detalles(db)["simulacion"]

    assert s["p50_mensual_kwh"][0] == 100000.0
    assert len(s["p50_mensual_kwh"]) == 12
    assert s["p50_anual_kwh"] == 1560000.0
    # Sin P90/P99 cargados no se inventa una serie a partir del P50.
    assert s["p90_mensual_kwh"] is None


def test_la_simulacion_no_llama_anual_a_una_serie_incompleta(db):
    """Sumar 3 meses y decir que es el año sería mentira; la serie igual viaja."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    _con_contrato(db, proy)
    db.execute(Proyecto.__table__.update()
               .where(Proyecto.__table__.c.id == proy.id)
               .values(p50_mensual_kwh="[100000, 110000, 120000]"))
    db.commit()

    s = _detalles(db)["simulacion"]

    assert len(s["p50_mensual_kwh"]) == 3
    assert s["p50_anual_kwh"] is None


def test_la_ficha_completa_no_hace_una_consulta_por_planta(db):
    """Toda la ficha se precarga por lotes (_opciones_proyecto): si costara una
    consulta por planta, con el volumen real la respuesta se cae. Es la misma
    garantía que ya tenía la vista por planta."""
    def _planta(i):
        proy = _proyecto(db, nombre_comercial=f"Planta {i:02d}", municipio="Corozal")
        _info_tecnica(db, proy, marca_paneles="Trina", cantidad_inversores=5)
        _inversor(db, proy, nombre="Inversor 1", potencia_nominal_kw=300)
        db.add(Frontera(proyecto_id=proy.id, nombre_frontera=f"FN {i}",
                        codigo_frontera=f"Frt{i:05d}", tipo_frontera="generacion"))
        ppa = PPAContrato(numero_codigo_contrato=f"UNG-{i:03d}", tipo_contrato="compra",
                          fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2032, 12, 31))
        db.add(ppa); db.flush()
        _enlazar(db, ppa, proy)
        _oferta(db, planta_nombre=f"Planta {i:02d}", estado="operando",
                ppa_contrato_id=ppa.id)
        db.commit()

    for i in range(2):
        _planta(i)

    consultas = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*a, **kw):
        consultas["n"] += 1

    ppas_del_pipeline(db, hoy=HOY)
    con_dos = consultas["n"]

    for i in range(2, 10):
        _planta(i)
    consultas["n"] = 0
    nodos = ppas_del_pipeline(db, hoy=HOY)
    con_diez = consultas["n"]          # leerlo ANTES de cualquier otra llamada

    assert len(nodos) == 10
    assert con_diez == con_dos, (
        f"{con_dos} consultas con 2 plantas y {con_diez} con 10: hay N+1")
