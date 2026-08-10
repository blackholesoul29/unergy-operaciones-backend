"""GET /comercial/proyectos-operando — las plantas operando para otra plataforma.

Lo que se protege acá:

  · el universo: SOLO la etapa 'operando' del pipeline comercial, que es lo que
    se ve en /comercial filtrando por esa etapa;
  · una fila por PLANTA, no por oferta — una planta con oferta de compra de
    energía y de servicios sale una sola vez, con los dos códigos;
  · la generación promedio es la MEDIDA (proyectos.gen_mensual_promedio_mwh, la
    ventana móvil de 30 días), no la estimada, y su origen viaja al lado;
  · la fecha de inicio de comercialización NO se rellena con la del contrato ni
    con la de entrada en operación: son tres hechos distintos;
  · el contrato de energía sale de la oferta de compra; si la oferta no quedó
    enlazada, del PPA vigente de la planta;
  · nada de N+1: quien integra va a llamar esto en cada refresco.
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
from app.services.comercial import (
    duracion_contrato, fila_operando, proyectos_operando,
)


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
        GeneracionDiaria.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
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

def test_solo_devuelve_las_plantas_en_etapa_operando(db):
    """Es lo que Juan pidió: la API siempre trae los proyectos operando. Una
    oferta firmada todavía no opera y una terminada ya dejó de operar."""
    _oferta(db, planta_nombre="Opera", estado="operando")
    _oferta(db, planta_nombre="Recién firmada", estado="firmado")
    _oferta(db, planta_nombre="Ya terminó", estado="terminado")
    _oferta(db, planta_nombre="Se cayó", estado="declinado")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY)

    assert [f["nombre"] for f in filas] == ["Opera"]


def test_sin_ofertas_operando_devuelve_lista_vacia(db):
    _oferta(db, planta_nombre="Firmada", estado="firmado")
    db.commit()
    assert proyectos_operando(db, hoy=HOY) == []


def test_una_oportunidad_borrada_no_aporta_plantas(db):
    """El borrado lógico del CRM tiene que sacar la planta de la integración: si
    no, otra plataforma sigue mostrando un negocio que acá ya no existe."""
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, planta_nombre="Fantasma")
    op.deleted_at = dt.datetime(2026, 7, 1)
    db.commit()

    assert proyectos_operando(db, hoy=HOY) == []


def test_un_proyecto_borrado_no_aparece_aunque_la_oferta_siga_viva(db):
    proy = _proyecto(db, nombre_comercial="Planta borrada",
                     deleted_at=dt.datetime(2026, 7, 1))
    _oferta(db, planta_nombre="Planta borrada", proyecto_id=proy.id)
    db.commit()

    assert proyectos_operando(db, hoy=HOY) == []


# ── Una fila por planta ──────────────────────────────────────────────────────

def test_dos_ofertas_de_la_misma_planta_son_una_sola_fila(db):
    """Una planta suele tener la oferta de compra de energía y la de servicios.
    Si salieran como dos filas, quien integra tendría que deduplicar — y el
    pedido era "los proyectos", no "las ofertas"."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            numero_oferta="OP.COM No.0051-3-2026")
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            numero_oferta="OP.REPCGM No.0058-07-2025")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY)

    assert len(filas) == 1
    assert filas[0]["nombre"] == "GD Catedral"
    assert {o["tipo"] for o in filas[0]["ofertas"]} == {
        "compra_energia", "servicios_operacionales"}
    assert {o["codigo_seguimiento"] for o in filas[0]["ofertas"]} == {
        "OP.COM No.0051-3-2026", "OP.REPCGM No.0058-07-2025"}


def test_una_planta_sin_proyecto_igual_aparece(db):
    """Aparece en /comercial, así que tiene que aparecer acá. `proyecto_id` en
    null es la señal de que la planta todavía no existe en la plataforma."""
    _oferta(db, planta_nombre="GD Rio Pamplonita", municipio="Cúcuta",
            departamento="Norte de Santander")
    db.commit()

    fila = proyectos_operando(db, hoy=HOY)[0]

    assert fila["proyecto_id"] is None
    assert fila["nombre"] == "GD Rio Pamplonita"
    assert fila["ubicacion"]["texto"] == "Cúcuta, Norte de Santander"
    assert fila["fuentes"]["nombre"] == "oferta"


def test_el_codigo_viejo_OF_se_muestra_estandarizado_a_OP(db):
    _oferta(db, planta_nombre="Bayunca", numero_oferta="OF.COM No.0012-5-2025")
    db.commit()

    fila = proyectos_operando(db, hoy=HOY)[0]
    assert fila["ofertas"][0]["codigo_seguimiento"] == "OP.COM No.0012-5-2025"


def test_las_filas_salen_ordenadas_por_nombre(db):
    _oferta(db, planta_nombre="Zulia")
    _oferta(db, planta_nombre="Aguachica")
    _oferta(db, planta_nombre="Marimonda")
    db.commit()

    assert [f["nombre"] for f in proyectos_operando(db, hoy=HOY)] == [
        "Aguachica", "Marimonda", "Zulia"]


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
                mwh_mes_estimado=None, p50_mensual_kwh=None,
                fecha_inicio_comercializacion=None, fecha_entrada_operacion=None,
                latitud=None, longitud=None, potencia_instalada_kwp=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_el_proyecto_manda_sobre_lo_declarado_en_la_oferta():
    """Cuando la planta ya existe, el Proyecto es la verdad: lo declarado en la
    oferta fue una foto del momento de la venta y pudo envejecer."""
    f = fila_operando([_of(planta_nombre="Catedral (borrador)", municipio="Sincelejo")],
                      proyecto=_py(nombre_comercial="GD Catedral", municipio="Corozal"),
                      hoy=HOY)

    assert f["nombre"] == "GD Catedral" and f["ubicacion"]["municipio"] == "Corozal"
    assert f["fuentes"]["municipio"] == "proyecto"


def test_la_cascada_es_por_campo_no_por_entidad():
    """Un Proyecto a medio diligenciar no debe borrar lo que la oferta sí sabe."""
    f = fila_operando([_of(municipio="Sincelejo", departamento="Sucre")],
                      proyecto=_py(nombre_comercial="GD Catedral", municipio="Corozal"),
                      hoy=HOY)

    assert f["ubicacion"]["municipio"] == "Corozal"
    assert f["fuentes"]["municipio"] == "proyecto"
    assert f["ubicacion"]["departamento"] == "Sucre"
    assert f["fuentes"]["departamento"] == "oferta"


def test_el_operador_de_red_sale_del_catalogo():
    f = fila_operando([_of()],
                      proyecto=_py(operador_red_legal="AFINIA S.A.S. E.S.P.",
                                   operador_red_id=3), hoy=HOY)

    assert f["operador_red"] == "AFINIA S.A.S. E.S.P." and f["operador_red_id"] == 3
    assert f["fuentes"]["operador_red"] == "proyecto"


def test_sin_catalogo_el_operador_cae_a_lo_declarado_en_la_oferta():
    f = fila_operando([_of(operador_red_id=7)], operador_oferta="CENS S.A. E.S.P.",
                      hoy=HOY)

    assert f["operador_red"] == "CENS S.A. E.S.P." and f["operador_red_id"] == 7
    assert f["fuentes"]["operador_red"] == "oferta"


def test_el_nombre_y_el_id_del_operador_salen_de_la_misma_oferta(db):
    """Con dos ofertas que declaran operadores distintos, el nombre y el id
    tienen que describir al mismo operador. Resolver el nombre por un lado y el
    id por otro daba un par incoherente."""
    essa = OperadorRed(nombre_legal="ESSA S.A. E.S.P.")
    cens = OperadorRed(nombre_legal="CENS S.A. E.S.P.")
    db.add_all([essa, cens]); db.flush()
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, planta_nombre="GD Rio Pamplonita",
            tipo="compra_energia", operador_red_id=essa.id)
    _oferta(db, oportunidad=op, planta_nombre="GD Rio Pamplonita",
            tipo="servicios_operacionales", operador_red_id=cens.id)
    db.commit()

    # sin proyecto vinculado, las dos ofertas caen en grupos distintos: se
    # comprueba en cada uno que el par (nombre, id) sea consistente
    for fila in proyectos_operando(db, hoy=HOY):
        esperado = {essa.id: "ESSA S.A. E.S.P.", cens.id: "CENS S.A. E.S.P."}
        assert fila["operador_red"] == esperado[fila["operador_red_id"]]


def test_como_ultimo_recurso_vale_el_texto_libre_legacy_del_proyecto():
    """`proyectos.operador_red` es texto sin validar y está declarado legacy,
    pero en filas viejas es el único dato que hay. Se marca como tal para que
    quien integre sepa que ese nombre no salió del catálogo."""
    f = fila_operando([_of()], proyecto=_py(operador_red="Afinia"), hoy=HOY)

    assert f["operador_red"] == "Afinia" and f["operador_red_id"] is None
    assert f["fuentes"]["operador_red"] == "proyecto_legacy"


def test_sin_ningun_dato_los_campos_y_sus_fuentes_quedan_en_null():
    """"Todavía no lo sabemos" y "no aplica" tienen que verse distinto."""
    f = fila_operando([_of()], hoy=HOY)

    for campo in ("nombre", "municipio", "departamento", "operador_red",
                  "gen_promedio_mensual", "fecha_inicio_comercializacion",
                  "contrato_energia"):
        assert f["fuentes"][campo] is None, campo
    assert f["ubicacion"]["texto"] is None
    assert f["gen_promedio_mensual_mwh"] is None


# ── Generación mensual promedio ──────────────────────────────────────────────

def test_la_generacion_promedio_es_la_medida_y_dice_sobre_cuantos_dias():
    """Es el indicador que se agregó a los proyectos: la ventana móvil de 30
    días. Sin `dias_con_datos` nadie sabe si el promedio salió de 30 días o de
    27, y no valen lo mismo."""
    f = fila_operando([_of()], proyecto=_py(
        gen_mensual_promedio_mwh=178.4, gen_promedio_origen="api",
        gen_promedio_dias=30, gen_promedio_desde=dt.date(2026, 7, 10),
        gen_promedio_hasta=dt.date(2026, 8, 8)), hoy=HOY)

    assert f["gen_promedio_mensual_mwh"] == 178.4
    assert f["gen_promedio_mensual_kwh"] == 178400.0
    assert f["gen_promedio_origen"] == "medido"
    assert f["fuentes"]["gen_promedio_mensual"] == "medido"
    assert f["gen_promedio_detalle"]["dias_con_datos"] == 30
    assert f["gen_promedio_detalle"]["ventana_desde"] == dt.date(2026, 7, 10)


def test_un_promedio_cargado_a_mano_se_marca_manual():
    """Una planta recién energizada no tiene histórico y su promedio lo carga una
    persona. Presentarlo como medido sería mentir sobre su confiabilidad."""
    f = fila_operando([_of()], proyecto=_py(gen_mensual_promedio_mwh=95.0,
                                            gen_promedio_origen="manual"), hoy=HOY)

    assert f["gen_promedio_mensual_mwh"] == 95.0
    assert f["gen_promedio_origen"] == "manual"


def test_sin_promedio_medido_cae_a_la_proyeccion_del_proyecto():
    f = fila_operando([_of()], proyecto=_py(mwh_mes_estimado=120.5), hoy=HOY)
    assert f["gen_promedio_mensual_mwh"] == 120.5
    assert f["gen_promedio_origen"] == "estimado"


def test_sin_proyeccion_cae_al_promedio_de_la_curva_p50():
    """p50_mensual_kwh son 12 valores mensuales en kWh; el resultado va en MWh."""
    f = fila_operando([_of()], proyecto=_py(p50_mensual_kwh=[100_000.0] * 12), hoy=HOY)
    assert f["gen_promedio_mensual_mwh"] == 100.0
    assert f["gen_promedio_origen"] == "estimado"


def test_el_p50_guardado_como_texto_json_tambien_sirve():
    """Plantas viejas (Baraya, La Cumbia) lo tienen como STRING JSON dentro del
    JSONB. Recorrer ese string da caracteres y `float('[')` reventaba la lista."""
    f = fila_operando([_of()],
                      proyecto=_py(p50_mensual_kwh="[100000.0, 100000.0, 220000.0]"),
                      hoy=HOY)
    assert f["gen_promedio_mensual_mwh"] == 140.0


def test_sin_proyecto_vale_lo_declarado_en_la_oferta_convertido_a_mwh():
    """El CRM habla en kWh/mes y la plataforma en MWh: la conversión se hace acá
    una vez, no en cada integración."""
    f = fila_operando([_of(energia_promedio_kwh_mes=174000)], hoy=HOY)

    assert f["gen_promedio_mensual_mwh"] == 174.0
    assert f["gen_promedio_mensual_kwh"] == 174000.0
    assert f["gen_promedio_origen"] == "declarado"


def test_el_promedio_medido_le_gana_a_la_proyeccion(db):
    """Con las dos cargadas, manda el número medido: describe a la planta hoy."""
    f = fila_operando([_of(energia_promedio_kwh_mes=999_000)],
                      proyecto=_py(gen_mensual_promedio_mwh=178.4,
                                   gen_promedio_origen="api",
                                   mwh_mes_estimado=200.0,
                                   p50_mensual_kwh=[300_000.0] * 12), hoy=HOY)
    assert f["gen_promedio_mensual_mwh"] == 178.4


# ── Fecha de inicio de comercialización ──────────────────────────────────────

def test_la_fecha_de_comercializacion_sale_del_proyecto():
    f = fila_operando([_of()], proyecto=_py(
        fecha_inicio_comercializacion=dt.date(2026, 2, 12)), hoy=HOY)

    assert f["fecha_inicio_comercializacion"] == dt.date(2026, 2, 12)
    assert f["fuentes"]["fecha_inicio_comercializacion"] == "proyecto"


def test_la_comercializacion_no_se_rellena_con_la_fecha_del_contrato():
    """Inicio de comercialización = primer día con generación real. El contrato
    puede arrancar antes o después, y la entrada en operación es otra cosa más.
    Rellenar uno con otro haría que el campo no sirva para nada."""
    ppa = types.SimpleNamespace(id=1, fecha_inicio=dt.date(2026, 1, 1),
                                fecha_fin=dt.date(2032, 12, 31),
                                numero_codigo_contrato=None, nombre_interno=None,
                                tipo_contrato="compra", comprador_nombre=None,
                                vendedor_nombre=None, cantidad_minima_kwh_mes=None)
    f = fila_operando([_of()], proyecto=_py(fecha_entrada_operacion=dt.date(2026, 3, 1)),
                      ppa=ppa, hoy=HOY)

    assert f["fecha_inicio_comercializacion"] is None
    assert f["fuentes"]["fecha_inicio_comercializacion"] is None
    # los hechos vecinos sí viajan, cada uno en su casilla
    assert f["fecha_entrada_operacion"] == dt.date(2026, 3, 1)
    assert f["contrato_energia"]["fecha_inicio"] == dt.date(2026, 1, 1)


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


def test_sin_contrato_la_duracion_queda_en_null_sin_reventar():
    d = duracion_contrato(None, None, hoy=HOY)
    assert d["duracion_meses"] is None and d["duracion_texto"] is None
    assert d["vigente"] is None


def test_el_contrato_sale_del_ppa_enlazado_a_la_oferta(db):
    proy = _proyecto(db, nombre_comercial="Catedral")
    ppa = _ppa(db, numero_codigo_contrato="UNG-2026-014",
               fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31),
               tipo_contrato="compra", comprador_nombre="UNERGY S.A.S.")
    _oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id)
    db.commit()

    c = proyectos_operando(db, hoy=HOY)[0]["contrato_energia"]

    assert c["ppa_contrato_id"] == ppa.id
    assert c["numero_codigo_contrato"] == "UNG-2026-014"
    assert c["duracion_meses"] == 83 and c["duracion_texto"] == "6 años y 11 meses"
    assert c["vigente"] is True


def test_sin_ppa_enlazado_se_usa_el_contrato_vigente_de_la_planta(db):
    """Las plantas anteriores al CRM tienen contrato pero su oferta no quedó
    enlazada. Sin este respaldo, "tiempo del contrato" saldría null justo en las
    plantas más viejas, que son las que sí tienen contrato."""
    proy = _proyecto(db, nombre_comercial="Bayunca")
    _ppa(db, proyecto=proy, numero_codigo_contrato="VIEJO",
         fecha_inicio=dt.date(2019, 1, 1), fecha_fin=dt.date(2021, 12, 31))
    _ppa(db, proyecto=proy, numero_codigo_contrato="VIGENTE",
         fecha_inicio=dt.date(2025, 11, 20), fecha_fin=dt.date(2030, 12, 31))
    _oferta(db, proyecto_id=proy.id)
    db.commit()

    c = proyectos_operando(db, hoy=HOY)[0]["contrato_energia"]

    assert c["numero_codigo_contrato"] == "VIGENTE"
    assert c["vigente"] is True


def test_manda_el_contrato_de_la_oferta_de_compra_de_energia(db):
    """Una planta con oferta de servicios y de compra tiene dos contratos. "El
    contrato de energía" es el de la compra; el de servicios es otra cosa."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    ppa_energia = _ppa(db, numero_codigo_contrato="ENERGIA",
                       fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2033, 12, 31))
    ppa_otro = _ppa(db, numero_codigo_contrato="OTRO",
                    fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2027, 12, 31))
    # a propósito, la de servicios se crea PRIMERO (id menor)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            ppa_contrato_id=ppa_otro.id)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            ppa_contrato_id=ppa_energia.id)
    db.commit()

    c = proyectos_operando(db, hoy=HOY)[0]["contrato_energia"]
    assert c["numero_codigo_contrato"] == "ENERGIA"


def test_un_contrato_borrado_no_alimenta_la_fila(db):
    proy = _proyecto(db, nombre_comercial="Marimonda")
    ppa = _ppa(db, proyecto=proy, fecha_inicio=dt.date(2026, 1, 1),
               fecha_fin=dt.date(2030, 12, 31), deleted_at=dt.datetime(2026, 7, 1))
    _oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id)
    db.commit()

    fila = proyectos_operando(db, hoy=HOY)[0]
    assert fila["contrato_energia"]["ppa_contrato_id"] is None
    assert fila["fuentes"]["contrato_energia"] is None


# ── Filtro y forma de la respuesta ───────────────────────────────────────────

def test_el_filtro_q_busca_por_planta_cliente_y_codigo(db):
    cli = _cliente(db, "PELLETCO S.A.S.")
    _oferta(db, oportunidad=_oportunidad(db, cli), planta_nombre="Bayunca",
            numero_oferta="OP.COM No.0012-5-2025")
    _oferta(db, planta_nombre="Marimonda")
    db.commit()

    assert [f["nombre"] for f in proyectos_operando(db, q="bayun", hoy=HOY)] == ["Bayunca"]
    assert [f["nombre"] for f in proyectos_operando(db, q="pelletco", hoy=HOY)] == ["Bayunca"]
    assert [f["nombre"] for f in proyectos_operando(db, q="0012", hoy=HOY)] == ["Bayunca"]
    assert proyectos_operando(db, q="no existe", hoy=HOY) == []


def test_la_fila_trae_siempre_las_mismas_llaves(db):
    """Quien integra no debería programar defensivamente contra llaves ausentes
    —sí contra valores null—, así que la forma no puede depender de los datos."""
    _oferta(db, planta_nombre="Pelada")
    proy = _proyecto(db, nombre_comercial="Completa", municipio="Corozal",
                     departamento="Sucre", gen_mensual_promedio_mwh=178.4,
                     gen_promedio_origen="api",
                     fecha_inicio_comercializacion=dt.date(2026, 2, 12))
    _oferta(db, proyecto_id=proy.id)
    db.commit()

    filas = proyectos_operando(db, hoy=HOY)
    assert set(filas[0]) == set(filas[1])
    assert set(filas[0]["fuentes"]) == set(filas[1]["fuentes"])
    assert "_principal" not in filas[0]


def test_no_hace_una_consulta_por_planta(db):
    """Quien integra va a llamar esto en cada refresco de su tablero: si costara
    una consulta por planta, se cae con el volumen real."""
    def _planta(i):
        proy = _proyecto(db, nombre_comercial=f"Planta {i:02d}", municipio="Corozal",
                         gen_mensual_promedio_mwh=100 + i)
        ppa = _ppa(db, proyecto=proy, fecha_inicio=dt.date(2026, 1, 1),
                   fecha_fin=dt.date(2030, 12, 31))
        _oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id)
        db.commit()

    for i in range(2):
        _planta(i)

    consultas = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*a, **kw):
        consultas["n"] += 1

    proyectos_operando(db, hoy=HOY)
    con_dos = consultas["n"]

    for i in range(2, 10):
        _planta(i)
    consultas["n"] = 0
    filas = proyectos_operando(db, hoy=HOY)
    con_diez = consultas["n"]      # leerlo ANTES de cualquier otra llamada

    assert len(filas) == 10
    assert con_diez == con_dos, (
        f"{con_dos} consultas con 2 plantas y {con_diez} con 10: hay N+1")


# ── La ruta HTTP ─────────────────────────────────────────────────────────────
# Se monta un app mínimo con solo este router, sin arrancar app.main.

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
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return TestClient(app)


def test_la_ruta_devuelve_el_sobre_con_total_e_items(db, client):
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()
    proy = _proyecto(db, nombre_comercial="GD Catedral", municipio="Corozal",
                     departamento="Sucre", operador_red_id=orr.id,
                     gen_mensual_promedio_mwh=178.4, gen_promedio_origen="api",
                     gen_promedio_dias=30,
                     fecha_inicio_comercializacion=dt.date(2026, 2, 12),
                     potencia_instalada_kwp=999.9)
    ppa = _ppa(db, numero_codigo_contrato="UNG-2026-014",
               fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    _oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id,
            numero_oferta="OP.COM No.0051-3-2026")
    db.commit()

    r = client.get("/api/v1/comercial/proyectos-operando")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "operando" and cuerpo["total"] == 1
    fila = cuerpo["items"][0]
    assert fila["nombre"] == "GD Catedral"
    assert fila["ubicacion"]["texto"] == "Corozal, Sucre"
    assert fila["operador_red"] == "AFINIA S.A.S. E.S.P."
    assert fila["gen_promedio_mensual_mwh"] == 178.4
    assert fila["gen_promedio_mensual_kwh"] == 178400.0
    assert fila["fecha_inicio_comercializacion"] == "2026-02-12"
    assert fila["contrato_energia"]["duracion_meses"] == 83
    assert fila["contrato_energia"]["duracion_texto"] == "6 años y 11 meses"
    assert fila["ofertas"][0]["codigo_seguimiento"] == "OP.COM No.0051-3-2026"


def test_la_ruta_acepta_el_filtro_q(db, client):
    _oferta(db, planta_nombre="Bayunca")
    _oferta(db, planta_nombre="Marimonda")
    db.commit()

    r = client.get("/api/v1/comercial/proyectos-operando", params={"q": "mari"})

    assert r.status_code == 200, r.text
    assert [f["nombre"] for f in r.json()["items"]] == ["Marimonda"]


def test_la_ruta_no_la_captura_el_path_param_de_oferta(db, client):
    """`/comercial/ofertas/{oferta_id}` está tipado int; si la ruta nueva quedara
    tapada por otra, esto daría 422 en vez de 200."""
    r = client.get("/api/v1/comercial/proyectos-operando")
    assert r.status_code == 200, r.text


def test_sin_datos_la_ruta_devuelve_un_sobre_vacio_no_un_404(db, client):
    r = client.get("/api/v1/comercial/proyectos-operando")
    assert r.status_code == 200
    assert r.json()["total"] == 0 and r.json()["items"] == []


def test_generado_en_trae_el_offset_real_de_colombia(db, client):
    """col_now() da la hora de Colombia pero etiquetada UTC: serializada dice
    "+00:00" sobre una hora que es -05:00, y quien la parsee se corre cinco
    horas. Lo que sale hacia afuera usa ahora_colombia()."""
    r = client.get("/api/v1/comercial/proyectos-operando")
    assert r.json()["generado_en"].endswith("-05:00"), r.json()["generado_en"]
