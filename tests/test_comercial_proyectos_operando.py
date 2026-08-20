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
from app.services.comercial import (
    ETAPAS_CONSULTABLES, duracion_contrato, fila_operando, proyectos_operando,
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

def test_devuelve_las_plantas_firmadas_y_operando_con_su_etapa(db):
    """Las dos etapas de negocio cerrado. El resto del pipeline queda afuera: una
    oferta apenas enviada no es un compromiso, una terminada ya se venció y una
    declinada no existe como negocio."""
    _oferta(db, planta_nombre="Opera", estado="operando")
    _oferta(db, planta_nombre="Recién firmada", estado="firmado")
    _oferta(db, planta_nombre="En negociación", estado="contrato")
    _oferta(db, planta_nombre="Ya terminó", estado="terminado")
    _oferta(db, planta_nombre="Se cayó", estado="declinado")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY)

    assert {f["nombre"]: f["estado_pipeline"] for f in filas} == {
        "Opera": "operando", "Recién firmada": "firmado"}


def test_se_puede_pedir_solo_operando(db):
    """El comportamiento original sigue disponible acotando la etapa."""
    _oferta(db, planta_nombre="Opera", estado="operando")
    _oferta(db, planta_nombre="Recién firmada", estado="firmado")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY, estados=("operando",))
    assert [f["nombre"] for f in filas] == ["Opera"]


def test_la_etapa_de_la_planta_es_la_mas_avanzada_de_sus_ofertas(db):
    """Una planta con la energía operando y los servicios recién firmados ESTÁ
    operando: decir 'firmado' diría que todavía no entrega energía."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            estado="firmado")
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            estado="operando")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY)

    assert len(filas) == 1 and filas[0]["estado_pipeline"] == "operando"
    # y las dos etapas por oferta siguen visibles
    assert {o["estado"] for o in filas[0]["ofertas"]} == {"firmado", "operando"}


def test_filtrar_por_firmado_no_trae_una_planta_que_ya_opera(db):
    """El filtro es por la etapa RESUELTA de la planta, no por "tiene alguna
    oferta en esa etapa". Si trajera a la que opera, los conteos de las dos
    etapas por separado sumarían más que el total, y quien integre vería una
    planta operando etiquetada como firmada."""
    mixta = _proyecto(db, nombre_comercial="GD Biosolar")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=mixta.id, tipo="compra_energia",
            estado="operando")
    _oferta(db, oportunidad=op, proyecto_id=mixta.id, tipo="servicios_operacionales",
            estado="firmado")
    sola = _proyecto(db, nombre_comercial="GD Elektra")
    _oferta(db, proyecto_id=sola.id, estado="firmado")
    db.commit()

    solo_firmado = proyectos_operando(db, hoy=HOY, estados=("firmado",))
    solo_operando = proyectos_operando(db, hoy=HOY, estados=("operando",))
    todas = proyectos_operando(db, hoy=HOY)

    assert [f["nombre"] for f in solo_firmado] == ["GD Elektra"]
    assert [f["nombre"] for f in solo_operando] == ["GD Biosolar"]
    assert len(solo_firmado) + len(solo_operando) == len(todas)


def test_acotar_la_etapa_elige_plantas_pero_no_recorta_sus_ofertas(db):
    """La fila sigue trayendo todas sus ofertas cerradas: quien filtra por
    `operando` no debería perder de vista que la planta tiene servicios
    firmados."""
    proy = _proyecto(db, nombre_comercial="GD Biosolar")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            estado="operando")
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            estado="firmado")
    db.commit()

    fila = proyectos_operando(db, hoy=HOY, estados=("operando",))[0]

    assert {o["estado"] for o in fila["ofertas"]} == {"firmado", "operando"}


def test_sin_ofertas_cerradas_devuelve_lista_vacia(db):
    _oferta(db, planta_nombre="Apenas enviada", estado="oferta")
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
                p50_mensual_kwh=None,
                fecha_inicio_comercializacion=None, fecha_entrada_operacion=None,
                latitud=None, longitud=None, potencia_instalada_kwp=None,
                sub_project=None, estado=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


# ── Todo el pipeline, no solo el negocio cerrado ─────────────────────────────

def test_por_defecto_siguen_saliendo_solo_firmadas_y_operando(db):
    """Abrir el pipeline no cambia lo que devuelve la llamada sin filtros: quien
    ya integró contra firmado/operando no se entera."""
    _oferta(db, planta_nombre="Opera", estado="operando")
    _oferta(db, planta_nombre="Prospecto", estado="oportunidad")
    _oferta(db, planta_nombre="En negociación", estado="contrato")
    _oferta(db, planta_nombre="Ya terminó", estado="terminado")
    _oferta(db, planta_nombre="Se cayó", estado="declinado")
    db.commit()

    assert [f["nombre"] for f in proyectos_operando(db, hoy=HOY)] == ["Opera"]


def test_se_puede_pedir_cualquier_etapa_del_pipeline(db):
    _oferta(db, planta_nombre="Prospecto", estado="oportunidad")
    _oferta(db, planta_nombre="Se cayó", estado="declinado")
    _oferta(db, planta_nombre="Opera", estado="operando")
    db.commit()

    assert [f["nombre"] for f in
            proyectos_operando(db, hoy=HOY, estados=("declinado",))] == ["Se cayó"]
    assert [f["nombre"] for f in
            proyectos_operando(db, hoy=HOY, estados=ETAPAS_CONSULTABLES)] == [
        "Opera", "Prospecto", "Se cayó"]


def test_las_salidas_no_le_ganan_a_una_etapa_viva(db):
    """El riesgo de abrir el pipeline: `terminado` es el último de ETAPAS, así que
    tomarlo como "el más avanzado" haría que una planta que ESTÁ entregando
    energía y arrastra un contrato viejo terminado se reporte como terminada — y
    desaparezca de la consulta por defecto."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            estado="operando")
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            estado="terminado")
    db.commit()

    filas = proyectos_operando(db, hoy=HOY, estados=ETAPAS_CONSULTABLES)

    assert len(filas) == 1 and filas[0]["estado_pipeline"] == "operando"
    assert [f["nombre"] for f in proyectos_operando(db, hoy=HOY)] == ["GD Catedral"]


def test_sin_nada_vivo_la_planta_queda_en_su_salida(db):
    """Y entre dos salidas gana `terminado`: llegó a operar, la declinada nunca fue."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="compra_energia",
            estado="declinado")
    _oferta(db, oportunidad=op, proyecto_id=proy.id, tipo="servicios_operacionales",
            estado="terminado")
    db.commit()

    fila = proyectos_operando(db, hoy=HOY, estados=ETAPAS_CONSULTABLES)[0]

    assert fila["estado_pipeline"] == "terminado"


def test_una_planta_cae_en_una_sola_etapa_y_los_conteos_suman_el_total(db):
    """La propiedad que sostiene el filtro: sumar las etapas por separado tiene
    que dar el total, o quien integra ve la misma planta dos veces."""
    for i, e in enumerate(ETAPAS_CONSULTABLES):
        _oferta(db, planta_nombre=f"Planta {i}", estado=e)
    mixta = _proyecto(db, nombre_comercial="GD Mixta")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=mixta.id, estado="operando")
    _oferta(db, oportunidad=op, proyecto_id=mixta.id,
            tipo="servicios_operacionales", estado="contrato")
    db.commit()

    todas = proyectos_operando(db, hoy=HOY, estados=ETAPAS_CONSULTABLES)
    por_etapa = {e: proyectos_operando(db, hoy=HOY, estados=(e,))
                 for e in ETAPAS_CONSULTABLES}

    assert sum(len(v) for v in por_etapa.values()) == len(todas) == 8
    assert [f["nombre"] for f in por_etapa["operando"]] == ["GD Mixta", "Planta 4"]


def test_la_fila_trae_todas_sus_ofertas_aunque_se_acote_la_etapa(db):
    """Acotar elige plantas, no recorta su contenido: la oferta declinada de una
    planta que opera sigue visible."""
    proy = _proyecto(db, nombre_comercial="GD Catedral")
    op = _oportunidad(db)
    _oferta(db, oportunidad=op, proyecto_id=proy.id, estado="operando")
    _oferta(db, oportunidad=op, proyecto_id=proy.id,
            tipo="servicios_operacionales", estado="declinado")
    db.commit()

    fila = proyectos_operando(db, hoy=HOY, estados=("operando",))[0]

    assert {o["estado"] for o in fila["ofertas"]} == {"operando", "declinado"}


# ── La oferta vigente ────────────────────────────────────────────────────────

def test_la_oferta_vigente_es_la_que_sostiene_la_etapa_de_la_planta():
    """Invariante: si hay oferta vigente, su etapa es la de la planta. Sin esto,
    la fila diría 'operando' y señalaría una oferta en otra etapa."""
    f = fila_operando([_of(id=1, estado="operando"),
                       _of(id=2, estado="contrato", tipo="servicios_operacionales")],
                      hoy=HOY)

    assert f["oferta_vigente"]["oferta_id"] == 1
    assert f["oferta_vigente"]["estado"] == f["estado_pipeline"] == "operando"
    # y la lista completa no se toca
    assert [o["oferta_id"] for o in f["ofertas"]] == [1, 2]


def test_empatadas_en_la_misma_etapa_manda_la_de_compra_de_energia():
    """Una planta puede tener viva la de energía y la de servicios/CGM al tiempo.
    La que define el negocio es la de energía."""
    f = fila_operando([_of(id=7, estado="operando", tipo="servicios_operacionales"),
                       _of(id=9, estado="operando", tipo="compra_energia")], hoy=HOY)

    assert f["oferta_vigente"]["oferta_id"] == 9
    assert f["oferta_vigente"]["tipo"] == "compra_energia"


def test_sin_nada_vivo_no_hay_oferta_vigente():
    """`terminado` y `declinado` son salidas: no hay nada vigente que señalar.
    Las ofertas siguen en la lista."""
    f = fila_operando([_of(id=1, estado="terminado"),
                       _of(id=2, estado="declinado")], hoy=HOY)

    assert f["estado_pipeline"] == "terminado"
    assert f["oferta_vigente"] is None
    assert len(f["ofertas"]) == 2


def test_la_oferta_vigente_tiene_la_misma_forma_que_las_de_la_lista():
    """Quien integra escribe un solo lector para las dos."""
    f = fila_operando([_of(id=3, numero_oferta="OF.COM No.0051-3-2026")], hoy=HOY)

    assert f["oferta_vigente"] == f["ofertas"][0]
    # y el prefijo OF→OP sigue normalizándose en las dos
    assert f["oferta_vigente"]["codigo_seguimiento"] == "OP.COM No.0051-3-2026"


# ── Estado del proyecto (distinto de la etapa comercial) ─────────────────────

def test_el_estado_del_proyecto_viaja_con_su_etiqueta():
    """La etiqueta va al lado del slug para que quien integra la pinte tal cual y
    no arme su propio mapa de español, que se desalinearía al agregar un estado."""
    f = fila_operando([_of()], proyecto=_py(estado="en_operacion"), hoy=HOY)

    assert f["estado_proyecto"] == "en_operacion"
    assert f["estado_proyecto_label"] == "En operación"
    assert f["fuentes"]["estado_proyecto"] == "proyecto"


def test_sin_planta_vinculada_no_hay_estado_de_proyecto():
    """El estado vive en el Proyecto; una oferta que todavía no quedó vinculada a
    una planta cargada no lo tiene. `fuentes` separa "no aplica" de "no se sabe"."""
    f = fila_operando([_of(planta_nombre="GD Rio Pamplonita")], hoy=HOY)

    assert f["estado_proyecto"] is None
    assert f["estado_proyecto_label"] is None
    assert f["fuentes"]["estado_proyecto"] is None


def test_la_etapa_comercial_y_el_estado_del_proyecto_no_se_concilian():
    """Los dos estados pueden contradecirse (hay 5 plantas así en producción, con
    la oferta operando y el proyecto sin actualizar). Se muestran como están:
    inventar coherencia taparía el dato mal cargado en vez de dejarlo ver."""
    f = fila_operando([_of(estado="operando")],
                      proyecto=_py(estado="en_desarrollo"), hoy=HOY)

    assert f["estado_pipeline"] == "operando"
    assert f["estado_proyecto"] == "en_desarrollo"


def test_un_estado_de_proyecto_sin_etiqueta_no_rompe_la_fila():
    """Si algún día entra un estado que el catálogo de etiquetas no conoce, la
    fila sale igual con la etiqueta en null: nunca un 500 hacia quien integra."""
    f = fila_operando([_of()], proyecto=_py(estado="inventado"), hoy=HOY)

    assert f["estado_proyecto"] == "inventado"
    assert f["estado_proyecto_label"] is None


# ── API ID de Unergy ─────────────────────────────────────────────────────────

def test_el_api_id_unergy_es_el_sub_project():
    """Es el parámetro `sub_project` con el que se consulta /project_generation/
    en la API de Unergy, el mismo con el que se calcula el promedio."""
    f = fila_operando([_of()], proyecto=_py(sub_project="catedral"), hoy=HOY)

    assert f["api_id_unergy"] == "catedral"
    assert f["fuentes"]["api_id_unergy"] == "sub_project"


def test_sin_identificador_de_monitoreo_el_api_id_es_null():
    """Juan: "si lo tiene, si no entregarlo como nulo por ahora"."""
    f = fila_operando([_of()], proyecto=_py(), hoy=HOY)
    assert f["api_id_unergy"] is None
    assert f["fuentes"]["api_id_unergy"] is None


def test_una_planta_sin_proyecto_no_tiene_api_id():
    """El id vive en el Proyecto; una oferta sin planta cargada no lo tiene."""
    f = fila_operando([_of(planta_nombre="GD Rio Pamplonita")], hoy=HOY)
    assert f["api_id_unergy"] is None


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
                  "contrato_energia", "api_id_unergy"):
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


# ── Vincular ofertas a proyectos por nombre ──────────────────────────────────
# En producción, 28 de las 32 ofertas operando no tenían proyecto: el CRM se
# cargó desde hojas donde la planta es texto libre. Los casos de abajo son
# nombres REALES de esas dos listas.

from app.services.comercial import (  # noqa: E402
    proponer_vinculos_proyecto, vincular_proyectos,
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


def test_aplicado_de_verdad_escribe_el_vinculo(db):
    proy = _proyecto(db, nombre_comercial="La Catedral", municipio="Corozal",
                     gen_mensual_promedio_mwh=178.4, gen_promedio_origen="api")
    of = _oferta(db, planta_nombre="Catedral")
    db.commit()

    r = vincular_proyectos(db, dry_run=False)

    assert r["n_aplicados"] == 1
    db.refresh(of)
    assert of.proyecto_id == proy.id
    # y con eso la API ya devuelve los datos de la planta
    fila = proyectos_operando(db, hoy=HOY)[0]
    assert fila["ubicacion"]["municipio"] == "Corozal"
    assert fila["gen_promedio_mensual_mwh"] == 178.4


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


# ── La ruta HTTP ─────────────────────────────────────────────────────────────
#
# Los tests de la ruta viven en test_comercial_ppas_pipeline.py: desde 2026-08-18
# GET /comercial/proyectos-operando devuelve el árbol PPA → PROYECTOS → detalles
# y ya no la lista de plantas. Lo que queda en este archivo son los tests de
# `proyectos_operando()` como función, que sigue siendo la vista por PLANTA.
