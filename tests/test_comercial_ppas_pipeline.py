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
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
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
    assert ppa["es_borrador"] is True
    assert ppa["aparece_en_servicios"] is False
    assert ppa["estado_ppa"] == "borrador"


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
    assert nodo["es_borrador"] is False
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

    for nombre in ("Firmada sin cargar", "Operando sin cargar"):
        assert estados[nombre]["estado_ppa"] == "sin_contrato", nombre
        assert estados[nombre]["es_borrador"] is False, nombre
        assert estados[nombre]["aparece_en_servicios"] is False, nombre


def test_el_borrador_es_solo_de_las_etapas_previas_a_la_firma(db):
    """`es_borrador` significa 'contrato en preparación', y eso solo aplica antes
    de firmar."""
    _oferta(db, planta_nombre="En oferta", estado="oferta")
    _oferta(db, planta_nombre="En negociación", estado="contrato")
    db.commit()

    for n in ppas_del_pipeline(db, hoy=HOY):
        assert n["ppa"]["es_borrador"] is True, n["ppa"]["planta_declarada"]
        assert n["ppa"]["estado_ppa"] == "borrador"


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
    """El sobre trae los conteos por estado_ppa ya hechos: quien integra no tiene
    que recorrer la lista para saber cuántos borradores hay."""
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
    assert d["por_estado_ppa"] == {"borrador": 1, "firmado": 1}
    firmado = next(n for n in d["ppas"] if not n["ppa"]["es_borrador"])
    assert firmado["ppa"]["id"] == ppa.id
    assert firmado["proyectos"][0]["api_id_unergy"] == "catedral"
    assert firmado["proyectos"][0]["detalles"]["energia_promedio_origen"] == "medido"


def test_la_ruta_serializa_los_enums_como_slugs(db, client):
    """`estado` y `tipo` son Enum de SQLAlchemy: sin resolverlos, la respuesta
    saldría con el repr del enum en vez del slug."""
    _oferta(db, planta_nombre="GD Balmora", tipo="comunidad_energetica", estado="oferta")
    db.commit()

    ppa = client.get("/api/v1/comercial/proyectos-operando").json()["ppas"][0]["ppa"]

    assert ppa["etapa_comercial"] == "oferta"
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
    assert d["total"] == 0 and d["ppas"] == [] and d["por_estado_ppa"] == {}


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

    assert n["ppa"]["estado_ppa"] == "firmado"
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

    assert n["ppa"]["estado_ppa"] == "sin_contrato"
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
