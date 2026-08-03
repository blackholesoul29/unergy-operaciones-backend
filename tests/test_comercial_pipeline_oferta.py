"""El pipeline es de la OFERTA, no del cliente (2026-08-02).

Lo que se protege aquí es la razón del cambio: Tecni-plast tiene Margaritas 1
firmada y Margaritas 2 todavía en envío. Con la etapa colgando del cliente eso
no se podía representar — mover una arrastraba a la otra.
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
from app.models.contratos import PPAContrato, PPATarifa, ContratoServicio
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
)
from app.api.v1 import comercial as api
from app.schemas.comercial import (
    OportunidadCreate, OfertaCreate, EstadoChangeIn, FirmarOfertaIn,
)
from app.services.comercial import (
    ESTADOS_CON_ALERTA, cerrar_contratos_vencidos, estado_a_resultado, resumen_etapas,
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
        Proyecto.__table__, Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _tecniplast(db):
    """Un cliente con dos ofertas: Margaritas 1 y Margaritas 2."""
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    m1 = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Las Margaritas 1",
        numero_oferta="OP.COM No.0068-5-2026", estado="oferta"), db=db, current=ADMIN)
    m2 = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Las Margaritas 2",
        numero_oferta="OP.COM No.0069-5-2026", estado="oferta"), db=db, current=ADMIN)
    return op, m1, m2


# ── lógica pura ──────────────────────────────────────────────────────────────

def test_resultado_se_deriva_de_la_etapa():
    assert estado_a_resultado("oportunidad") == "pendiente"
    assert estado_a_resultado("contrato") == "pendiente"
    assert estado_a_resultado("firmado") == "aceptado"
    assert estado_a_resultado("operando") == "aceptado"
    assert estado_a_resultado("declinado") == "declinado"


def test_el_cliente_no_tiene_etapa_sino_un_conteo_de_las_de_sus_ofertas():
    """El negocio es la oferta. Colapsar las etapas de un cliente en una sola
    escondería justo lo que hay que ver."""
    assert resumen_etapas(["oferta", "firmado", "oferta"]) == {"oferta": 2, "firmado": 1}
    assert resumen_etapas([]) == {}


def test_las_etapas_de_cierre_no_alertan():
    assert ESTADOS_CON_ALERTA == frozenset({"oportunidad", "oferta", "contrato"})


def test_terminado_sigue_siendo_un_negocio_ganado():
    assert estado_a_resultado("terminado") == "aceptado"


# ── cierre automático por fecha_fin ──────────────────────────────────────────

def test_el_contrato_vencido_pasa_la_oferta_a_terminado(db):
    """El caso Agustín 1: suministro ene-mar 2026, ya acabó. Nadie lo mueve a
    mano — lo cierra el job leyendo la fecha_fin del PPA."""
    oferta = _pelletco(db)
    api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 3, 31),
        tarifa_base=308), db=db, current=ADMIN)
    db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta["id"]).update(
        {"estado": "operando"})
    db.commit()

    cerradas = cerrar_contratos_vencidos(db, hoy=dt.date(2026, 8, 2))
    assert len(cerradas) == 1
    fila = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta["id"]).first()
    assert fila.estado == "terminado" and fila.resultado == "aceptado"


def test_no_cierra_lo_que_todavia_esta_corriendo(db):
    oferta = _pelletco(db)
    api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2032, 12, 31),
        tarifa_base=308), db=db, current=ADMIN)
    db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta["id"]).update(
        {"estado": "operando"})
    db.commit()
    assert cerrar_contratos_vencidos(db, hoy=dt.date(2026, 8, 2)) == []


def test_no_cierra_una_firmada_que_aun_no_arranca(db):
    """Sonetel arranca en oct-2026: firmada, no operando, y no se toca."""
    oferta = _pelletco(db)
    api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 10, 31), fecha_fin=dt.date(2036, 12, 31),
        tarifa_base=320), db=db, current=ADMIN)
    assert cerrar_contratos_vencidos(db, hoy=dt.date(2026, 8, 2)) == []
    fila = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta["id"]).first()
    assert fila.estado == "firmado"


def test_cerrar_dos_veces_no_duplica_historial(db):
    oferta = _pelletco(db)
    api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 3, 31),
        tarifa_base=308), db=db, current=ADMIN)
    db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta["id"]).update(
        {"estado": "operando"})
    db.commit()
    cerrar_contratos_vencidos(db, hoy=dt.date(2026, 8, 2))
    assert cerrar_contratos_vencidos(db, hoy=dt.date(2026, 8, 2)) == []
    n = db.query(OportunidadEstadoHistorial).filter(
        OportunidadEstadoHistorial.estado_nuevo == "terminado").count()
    assert n == 1


# ── API ──────────────────────────────────────────────────────────────────────

def test_firmar_una_oferta_no_arrastra_a_su_hermana(db):
    op, m1, m2 = _tecniplast(db)
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="firmado"), db=db, current=ADMIN)

    por_codigo = {o["codigo_seguimiento"]: o for o in
                  api.list_ofertas(op["id"], db=db, current=ADMIN)}
    assert por_codigo["OP.COM No.0068-5-2026"]["estado"] == "firmado"
    assert por_codigo["OP.COM No.0069-5-2026"]["estado"] == "oferta"


def test_cambiar_la_etapa_reescribe_el_resultado(db):
    _op, m1, _m2 = _tecniplast(db)
    fila = api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="operando"),
                                     db=db, current=ADMIN)
    assert fila["estado"] == "operando" and fila["resultado"] == "aceptado"


def test_la_transicion_queda_en_el_historial_con_su_oferta(db):
    op, m1, _m2 = _tecniplast(db)
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="contrato"), db=db, current=ADMIN)
    hist = [h for h in api.get_oportunidad(op["id"], db=db, current=ADMIN)["historial"]
            if h["oferta_id"] == m1["id"]]
    # Una fila al crearla (nace en 'oferta') y otra por la transición.
    assert {"oferta", "contrato"} == {h["estado_nuevo"] for h in hist}
    paso = next(h for h in hist if h["estado_nuevo"] == "contrato")
    assert paso["estado_anterior"] == "oferta"


def test_la_ficha_del_cliente_desglosa_las_etapas_de_sus_ofertas(db):
    op, m1, _m2 = _tecniplast(db)
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="firmado"), db=db, current=ADMIN)
    fila = api.get_oportunidad(op["id"], db=db, current=ADMIN)
    assert fila["etapas"] == {"firmado": 1, "oferta": 1}
    assert "estado" not in fila          # el cliente no tiene etapa propia


def test_el_tablero_lista_cada_oferta_con_su_propia_etapa(db):
    op, m1, _m2 = _tecniplast(db)
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="firmado"), db=db, current=ADMIN)
    etapas = {o["codigo_seguimiento"]: o["estado"] for o in api.list_ofertas_todas(
        tipo=None, estado=None, resultado=None, q=None, solo_alerta=False,
        db=db, current=ADMIN)}
    assert etapas == {"OP.COM No.0068-5-2026": "firmado",
                      "OP.COM No.0069-5-2026": "oferta"}


def test_filtrar_por_etapa_devuelve_solo_esas_ofertas(db):
    _op, m1, _m2 = _tecniplast(db)
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="firmado"), db=db, current=ADMIN)
    firmadas = api.list_ofertas_todas(tipo=None, estado="firmado", resultado=None, q=None,
                                      solo_alerta=False, db=db, current=ADMIN)
    assert [o["codigo_seguimiento"] for o in firmadas] == ["OP.COM No.0068-5-2026"]


def test_una_oferta_firmada_deja_de_alertar(db):
    """La alerta cuenta desde que la oferta entró a SU etapa. Firmar reinicia el
    reloj y saca la oferta de las etapas que alertan."""
    op, m1, m2 = _tecniplast(db)
    viejo = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    for oid in (m1["id"], m2["id"]):
        db.query(OportunidadOferta).filter(OportunidadOferta.id == oid).update(
            {"estado_desde": viejo})
    db.commit()
    api.cambiar_estado_oferta(m1["id"], EstadoChangeIn(estado="firmado"), db=db, current=ADMIN)

    alertas = {o["codigo_seguimiento"]: o["alerta"] for o in api.list_ofertas_todas(
        tipo=None, estado=None, resultado=None, q=None, solo_alerta=False,
        db=db, current=ADMIN)}
    assert alertas["OP.COM No.0068-5-2026"] is False
    assert alertas["OP.COM No.0069-5-2026"] is True


def test_mover_el_negocio_entero_sigue_disponible(db):
    """El tablero viejo arrastra la tarjeta del cliente: eso mueve todas."""
    op, _m1, _m2 = _tecniplast(db)
    res = api.cambiar_estado(op["id"], EstadoChangeIn(estado="declinado"), db=db, current=ADMIN)
    assert res["ofertas_movidas"] == 2
    assert {o["estado"] for o in api.list_ofertas(op["id"], db=db, current=ADMIN)} == {"declinado"}


# ── la oferta evoluciona en contrato ─────────────────────────────────────────

def _pelletco(db):
    cli = Cliente(razon_social_nombre="PELLETCO S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    oferta = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="Catedral",
        numero_oferta="OP.COM No.0021-1-2026", estado="contrato"), db=db, current=ADMIN)
    return oferta


def test_firmar_crea_el_ppa_y_lo_enlaza_a_la_oferta(db):
    """Las condiciones NO se copian a la oferta: viven en el contrato."""
    oferta = _pelletco(db)
    res = api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31),
        cantidad_minima_kwh_mes=170000,
        indice_indexacion="IPP", periodo_indexacion_base="2025-10",
        precios_anuales=[{"anio": a, "precio": p} for a, p in
                         [(2026, 320), (2027, 305), (2028, 298), (2029, 291),
                          (2030, 290), (2031, 288), (2032, 288)]],
        carpeta_link="https://drive.google.com/drive/u/0/folders/1NvJ"),
        db=db, current=ADMIN)

    contrato = db.query(PPAContrato).filter(PPAContrato.id == res["ppa_contrato_id"]).first()
    assert contrato.fecha_fin == dt.date(2032, 12, 31)
    assert float(contrato.cantidad_minima_kwh_mes) == 170000
    assert contrato.periodo_indexacion_base == "2025-10"
    assert contrato.carpeta_link.endswith("1NvJ")
    # El código de seguimiento de la oferta se hereda como código del contrato.
    assert contrato.numero_codigo_contrato == "OP.COM No.0021-1-2026"
    assert res["oferta"]["ppa_contrato_id"] == contrato.id
    assert res["oferta"]["estado"] == "firmado"


def test_la_tabla_anual_se_expande_a_tarifas_mensuales_del_periodo(db):
    """Arranca el 12-feb-2026: ese año NO tiene tarifa de enero."""
    oferta = _pelletco(db)
    res = api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2027, 6, 30),
        precios_anuales=[{"anio": 2026, "precio": 320}, {"anio": 2027, "precio": 305}]),
        db=db, current=ADMIN)
    filas = db.query(PPATarifa).filter(PPATarifa.contrato_id == res["ppa_contrato_id"]).all()
    meses_2026 = sorted(f.mes for f in filas if f.año == 2026)
    meses_2027 = sorted(f.mes for f in filas if f.año == 2027)
    assert meses_2026 == list(range(2, 13))     # feb..dic
    assert meses_2027 == list(range(1, 7))      # ene..jun
    assert {float(f.tarifa) for f in filas if f.año == 2027} == {305.0}


def test_precio_fijo_sin_tabla_por_anio(db):
    """Bayunca: 300 $/kWh planos, sin indexación ni tabla."""
    oferta = _pelletco(db)
    res = api.firmar_oferta(oferta["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2025, 11, 20), fecha_fin=dt.date(2026, 12, 31),
        tarifa_base=300), db=db, current=ADMIN)
    contrato = db.query(PPAContrato).filter(PPAContrato.id == res["ppa_contrato_id"]).first()
    assert float(contrato.tarifa_base) == 300
    assert res["tarifas_creadas"] == 0


def test_firmar_dos_veces_no_crea_un_segundo_contrato(db):
    oferta = _pelletco(db)
    datos = FirmarOfertaIn(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 12, 31),
                           tarifa_base=300)
    api.firmar_oferta(oferta["id"], datos, db=db, current=ADMIN)
    with pytest.raises(HTTPException) as e:
        api.firmar_oferta(oferta["id"], datos, db=db, current=ADMIN)
    assert e.value.status_code == 409
    assert db.query(PPAContrato).count() == 1


def test_una_oferta_de_servicios_no_deriva_en_ppa(db):
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    oferta = api.create_oferta(op["id"], OfertaCreate(
        tipo="servicios_operacionales", estado="contrato"), db=db, current=ADMIN)
    with pytest.raises(HTTPException) as e:
        api.firmar_oferta(oferta["id"], FirmarOfertaIn(
            fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 12, 31),
            tarifa_base=300), db=db, current=ADMIN)
    assert e.value.status_code == 422


def test_periodo_al_reves_se_rechaza():
    with pytest.raises(ValueError):
        FirmarOfertaIn(fecha_inicio=dt.date(2026, 12, 31), fecha_fin=dt.date(2026, 1, 1),
                       tarifa_base=300)


def test_firmar_sin_ningun_precio_se_rechaza():
    with pytest.raises(ValueError):
        FirmarOfertaIn(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 12, 31))


def test_tabla_de_precios_con_anios_repetidos_se_rechaza():
    with pytest.raises(ValueError):
        FirmarOfertaIn(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2026, 12, 31),
                       precios_anuales=[{"anio": 2026, "precio": 320},
                                        {"anio": 2026, "precio": 310}])
