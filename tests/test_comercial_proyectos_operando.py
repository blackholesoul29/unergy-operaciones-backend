"""Duracion de contrato y vinculador de ofertas a plantas.

Este archivo probaba fila_operando() y proyectos_operando(), la version vieja de la
API de PPAs. Dejo de servirse el 2026-08-18: la reemplazo el arbol ppas[] de
ppas_del_pipeline(), que prueba test_comercial_ppas_pipeline.py. Esas dos funciones
y sus 52 tests se borraron en la Fase 0 del refactor del nucleo -- eran codigo muerto
que hacia creer que campos como estado_pipeline y oferta_vigente seguian vivos.

Lo que queda SI esta vivo, y hay que cuidarlo:

  - duracion_contrato() produce ppa.condiciones.{duracion_texto, meses_restantes,
    vigente}, que son campos del CONTRATO CONGELADO. Ver docs/refactor/05.
  - el vinculador de ofertas a plantas por nombre (proponer_vinculos_proyecto).
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
from app.services.comercial import duracion_contrato


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))
HOY = dt.date(2026, 8, 9)


@pytest.fixture
def db():
    # StaticPool + check_same_thread=False: los tests de ruteo usan TestClient,
    # que corre el endpoint síncrono en otro hilo. Con el pool por defecto ese
    # hilo recibe una conexión nueva, y en SQLite ":memory:" una conexión nueva
    # es una base VACÍA ("no such table: proyectos").
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        Cliente.__table__, ClienteDocumentoComercial.__table__, Contacto.__table__,
        Proyecto.__table__, Frontera.__table__, OperadorRed.__table__,
        # Las precarga _opciones_proyecto(): sin la tabla, la consulta revienta
        # con "no such table" aunque el test no las use.
        Portafolio.__table__, ProyectoInfoTecnica.__table__,
        ProyectoInversor.__table__,
        GeneracionDiaria.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
        Base.metadata.tables["oportunidad_oferta_proyectos"],
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


# ── Ayudas de armado ─────────────────────────────────────────────────────────

def _cliente(db, nombre="INVERSIONES TECNI-PLAST S.A.S."):
    c = Cliente(razon_social_nombre=nombre)
    db.add(c); db.flush()
    return c


def _oportunidad(db, cliente=None):
    cliente = cliente or _cliente(db)
    op = Oportunidad(cliente_id=cliente.id, estado="oportunidad")
    db.add(op); db.flush()
    return op


def _oferta(db, oportunidad=None, estado="operando", tipo="compra_energia", **kw):
    op = oportunidad or _oportunidad(db)
    of = OportunidadOferta(oportunidad_id=op.id, tipo=tipo, estado=estado, **kw)
    db.add(of); db.flush()
    return of


def _proyecto(db, **kw):
    p = Proyecto(**kw)
    db.add(p); db.flush()
    return p


def _ppa(db, proyecto=None, **kw):
    c = PPAContrato(**kw)
    db.add(c); db.flush()
    if proyecto is not None:
        db.execute(Base.metadata.tables["ppa_contrato_proyectos"].insert().values(
            contrato_id=c.id, proyecto_id=proyecto.id))
        db.flush()
    return c


# ── El universo: solo 'operando' ─────────────────────────────────────────────

# ── Una fila por planta ──────────────────────────────────────────────────────

# ── Cascada por campo ────────────────────────────────────────────────────────

def _of(**kw):
    """Oferta mínima para la lógica pura: solo los atributos que lee."""
    base = dict(id=1, oportunidad_id=1, tipo="compra_energia", estado="operando",
                planta_nombre=None, municipio=None, departamento=None,
                operador_red_id=None, energia_promedio_kwh_mes=None,
                numero_oferta=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _py(**kw):
    base = dict(id=10, nombre_comercial=None, municipio=None, departamento=None,
                operador_red=None, operador_red_id=None, operador_red_legal=None,
                gen_mensual_promedio_mwh=None, gen_promedio_origen=None,
                gen_promedio_dias=None, gen_promedio_desde=None,
                gen_promedio_hasta=None, gen_promedio_actualizado_en=None,
                p50_mensual_kwh=None,
                fecha_inicio_comercializacion=None, fecha_entrada_operacion=None,
                latitud=None, longitud=None, potencia_instalada_kwp=None,
                sub_project=None, estado=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


# ── Todo el pipeline, no solo el negocio cerrado ─────────────────────────────

# ── La oferta vigente ────────────────────────────────────────────────────────

# ── Estado del proyecto (distinto de la etapa comercial) ─────────────────────

# ── API ID de Unergy ─────────────────────────────────────────────────────────

# ── Generación mensual promedio ──────────────────────────────────────────────

# ── Fecha de inicio de comercialización ──────────────────────────────────────

# ── Tiempo del contrato de energía ───────────────────────────────────────────

def test_la_duracion_se_cuenta_en_meses_calendario():
    """Igual que ficha_operativa: el PPA se factura por mes, así que duración y
    facturación no pueden divergir."""
    d = duracion_contrato(dt.date(2026, 2, 12), dt.date(2032, 12, 31), hoy=HOY)
    assert d["duracion_meses"] == 83
    assert d["duracion_anios"] == 6.9
    assert d["duracion_texto"] == "6 años y 11 meses"


def test_la_duracion_en_texto_es_la_que_diria_una_persona():
    assert duracion_contrato(dt.date(2026, 1, 1), dt.date(2026, 12, 31),
                             hoy=HOY)["duracion_texto"] == "1 año"
    assert duracion_contrato(dt.date(2026, 1, 1), dt.date(2026, 1, 31),
                             hoy=HOY)["duracion_texto"] == "1 mes"
    assert duracion_contrato(dt.date(2026, 1, 1), dt.date(2026, 3, 31),
                             hoy=HOY)["duracion_texto"] == "3 meses"
    assert duracion_contrato(dt.date(2026, 1, 1), dt.date(2027, 3, 31),
                             hoy=HOY)["duracion_texto"] == "1 año y 3 meses"


def test_el_contrato_dice_cuanto_le_queda_y_si_esta_vigente():
    d = duracion_contrato(dt.date(2026, 2, 12), dt.date(2026, 12, 31), hoy=HOY)
    assert d["meses_restantes"] == 5      # ago…dic contando los dos extremos
    assert d["vigente"] is True

    vencido = duracion_contrato(dt.date(2020, 1, 1), dt.date(2021, 12, 31), hoy=HOY)
    assert vencido["meses_restantes"] == 0 and vencido["vigente"] is False


def test_un_contrato_firmado_que_no_arranco_le_queda_su_duracion_completa():
    """El caso de las plantas en etapa `firmado`. Contando desde hoy daría más
    meses restantes que meses de contrato, que es imposible."""
    d = duracion_contrato(dt.date(2027, 1, 1), dt.date(2032, 12, 31), hoy=HOY)

    assert d["duracion_meses"] == 72
    assert d["meses_restantes"] == 72       # no 77, que es la distancia hasta el fin
    assert d["meses_restantes"] <= d["duracion_meses"]
    assert d["vigente"] is False            # firmado, todavía no corre


def test_sin_contrato_la_duracion_queda_en_null_sin_reventar():
    d = duracion_contrato(None, None, hoy=HOY)
    assert d["duracion_meses"] is None and d["duracion_texto"] is None
    assert d["vigente"] is None


# ── Vincular ofertas a proyectos por nombre ──────────────────────────────────
# En producción, 28 de las 32 ofertas operando no tenían proyecto: el CRM se
# cargó desde hojas donde la planta es texto libre. Los casos de abajo son
# nombres REALES de esas dos listas.

from app.services.comercial import (  # noqa: E402
    ppas_del_pipeline, proponer_vinculos_proyecto, vincular_proyectos,
)


def test_propone_los_vinculos_de_los_nombres_reales_de_produccion(db):
    """"Catedral"/"La Catedral", "Taurus IX"/"GD Taurus IX", "Parque Solar
    Baraya"/"Minigranja Solar Baraya": la misma planta escrita distinto."""
    for nombre in ("La Catedral", "GD Taurus IX", "Minigranja Solar Baraya",
                   "GD San Pelayo", "GD Marimonda"):
        _proyecto(db, nombre_comercial=nombre)
    for planta in ("Catedral", "Taurus IX", "Parque Solar Baraya",
                   "San Pelayo", "Marimondá"):
        _oferta(db, planta_nombre=planta)
    db.commit()

    r = proponer_vinculos_proyecto(db)

    emparejados = {f["planta_nombre"]: f["proyecto_nombre"] for f in r["propuestos"]}
    assert emparejados == {
        "Catedral": "La Catedral",
        "Taurus IX": "GD Taurus IX",
        "Parque Solar Baraya": "Minigranja Solar Baraya",
        "San Pelayo": "GD San Pelayo",
        "Marimondá": "GD Marimonda",
    }
    assert r["n_sin_candidato"] == 0


def test_no_confunde_plantas_hermanas_numeradas(db):
    """"GD Polaris 1" y "GD Polaris 2" son plantas DISTINTAS. El prefijo "GD" es
    ruido, así que lo único que las separa es el número: si el matcher se las
    come, la API le muestra a una la generación de la otra."""
    _proyecto(db, nombre_comercial="GD Polaris 1")
    _proyecto(db, nombre_comercial="GD Polaris 2")
    _oferta(db, planta_nombre="Polaris 2")
    db.commit()

    r = proponer_vinculos_proyecto(db)

    assert [f["proyecto_nombre"] for f in r["propuestos"]] == ["GD Polaris 2"]


def test_no_adivina_cuando_dos_proyectos_quedan_parejos(db):
    """La guarda de ambigüedad del matcher compartido: mejor dejarlo para
    revisión manual que vincular la planta equivocada en silencio."""
    _proyecto(db, nombre_comercial="GD Isabela 1")
    _proyecto(db, nombre_comercial="GD Isabela 2")
    _oferta(db, planta_nombre="GD ISABELA")
    db.commit()

    r = proponer_vinculos_proyecto(db)

    assert r["n_propuestos"] == 0
    assert r["sin_candidato"][0]["planta_nombre"] == "GD ISABELA"


def test_lo_que_no_alcanza_el_umbral_se_reporta_con_su_puntaje(db):
    """Un nombre de EMPRESA en la casilla de la planta (pasa en las hojas) no
    tiene que vincularse a nada, pero sí tiene que verse en el reporte."""
    _proyecto(db, nombre_comercial="La Catedral")
    _oferta(db, planta_nombre="SOLUCIONES DE ENERGIA Y TELECOMUNICACIONES SONETEL S.A.S")
    db.commit()

    r = proponer_vinculos_proyecto(db)

    assert r["n_propuestos"] == 0
    fila = r["sin_candidato"][0]
    assert fila["planta_nombre"].startswith("SOLUCIONES")
    assert 0.0 <= fila["score"] < 0.72


def test_una_oferta_sin_nombre_de_planta_se_reporta_aparte(db):
    _proyecto(db, nombre_comercial="La Catedral")
    _oferta(db, planta_nombre=None)
    db.commit()

    r = proponer_vinculos_proyecto(db)
    assert r["n_sin_nombre"] == 1 and r["n_propuestos"] == 0


def test_por_defecto_mira_las_etapas_entregables(db):
    """Las que alimentan la API: firmado y operando. Una oferta que apenas se
    envió no vale la pena vincular todavía, pero `estados=None` la alcanza."""
    _proyecto(db, nombre_comercial="La Catedral")
    _proyecto(db, nombre_comercial="GD Taurus IX")
    _oferta(db, planta_nombre="Catedral", estado="oferta")       # etapa temprana
    _oferta(db, planta_nombre="Taurus IX", estado="firmado")
    db.commit()

    por_defecto = proponer_vinculos_proyecto(db)
    assert [f["planta_nombre"] for f in por_defecto["propuestos"]] == ["Taurus IX"]
    assert proponer_vinculos_proyecto(db, estados=None)["n_propuestos"] == 2


def test_en_seco_no_escribe_nada(db):
    """El default es dry_run: nadie vincula 28 plantas sin haber mirado la lista."""
    proy = _proyecto(db, nombre_comercial="La Catedral")
    of = _oferta(db, planta_nombre="Catedral")
    db.commit()

    r = vincular_proyectos(db, dry_run=True)

    assert r["n_propuestos"] == 1 and r["n_aplicados"] == 0
    db.refresh(of)
    assert of.proyecto_id is None
    assert proy.id is not None


def test_repetirlo_no_cambia_nada(db):
    """Idempotente: solo toca ofertas sin proyecto."""
    _proyecto(db, nombre_comercial="La Catedral")
    _oferta(db, planta_nombre="Catedral")
    db.commit()

    vincular_proyectos(db, dry_run=False)
    segunda = vincular_proyectos(db, dry_run=False)

    assert segunda["n_propuestos"] == 0 and segunda["n_aplicados"] == 0


def test_se_pueden_aceptar_unas_propuestas_y_descartar_otras(db):
    """Sin esto, aceptar 20 de 28 obligaría a subir el umbral y perder las
    buenas, o a vincular a mano una por una."""
    _proyecto(db, nombre_comercial="La Catedral")
    _proyecto(db, nombre_comercial="GD Taurus IX")
    buena = _oferta(db, planta_nombre="Catedral")
    otra = _oferta(db, planta_nombre="Taurus IX")
    db.commit()

    r = vincular_proyectos(db, dry_run=False, solo_ofertas=[buena.id])

    assert r["n_aplicados"] == 1
    db.refresh(buena); db.refresh(otra)
    assert buena.proyecto_id is not None
    assert otra.proyecto_id is None
    assert [f["oferta_id"] for f in r["omitidos_por_filtro"]] == [otra.id]


def test_un_proyecto_borrado_no_es_candidato(db):
    _proyecto(db, nombre_comercial="La Catedral", deleted_at=dt.datetime(2026, 7, 1))
    _oferta(db, planta_nombre="Catedral")
    db.commit()

    assert proponer_vinculos_proyecto(db)["n_propuestos"] == 0


def test_aplicado_de_verdad_escribe_el_vinculo(db):
    """El caso base de punta a punta: se aplica la propuesta y los datos de la
    planta quedan visibles en lo que la API sirve.

    Reconstruido en la Fase 0: la version anterior verificaba el resultado con
    proyectos_operando(), que era codigo muerto. Ahora se verifica contra
    ppas_del_pipeline(), que es el arbol que de verdad devuelve el endpoint.
    """
    proy = _proyecto(db, nombre_comercial="La Catedral", municipio="Corozal",
                     gen_mensual_promedio_mwh=178.4, gen_promedio_origen="api")
    of = _oferta(db, planta_nombre="Catedral")
    db.commit()

    r = vincular_proyectos(db, dry_run=False)

    assert r["n_aplicados"] == 1
    db.refresh(of)
    assert of.proyecto_id == proy.id

    detalles = ppas_del_pipeline(db, hoy=HOY)[0]["proyectos"][0]["detalles"]
    assert detalles["ubicacion"]["municipio"] == "Corozal"
    assert detalles["energia_promedio_mensual_mwh"] == 178.4
    assert detalles["energia_promedio_origen"] == "medido"


# ── La ruta HTTP ─────────────────────────────────────────────────────────────
#
# Los tests de la ruta viven en test_comercial_ppas_pipeline.py: desde 2026-08-18
# GET /comercial/proyectos-operando devuelve el árbol PPA → PROYECTOS → detalles
# y ya no la lista de plantas. La vista por planta que había acá se borró junto
# con proyectos_operando() en la Fase 0: ninguna ruta la servía.
