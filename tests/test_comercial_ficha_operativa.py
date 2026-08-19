"""Ficha operativa de la oferta (2026-08-03).

Los 6 parámetros que el equipo consume por API — nombre del proyecto, lugar,
operador de red, energía real, energía promedio, fecha de inicio de operación y
tiempo del contrato — solo existían colgados de `Proyecto`, y la mayoría de las
ofertas del pipeline no tienen proyecto (GD Rio Pamplonita y GD Las Margaritas 1
ni siquiera existen como planta). Lo que se protege aquí es la cascada
Proyecto → declarado en la oferta → null, y que consultarla no cueste una
consulta por oferta.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import create_engine, event, BigInteger
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


# ── Task 1: las columnas declaradas ──────────────────────────────────────────

def test_la_oferta_puede_declarar_lugar_operador_y_energia(db):
    """Sin Proyecto no hay dónde poner el lugar ni el operador. Estas cuatro
    columnas son ese lugar: la oferta declara lo que sabe y la API lo resuelve."""
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()

    of = OportunidadOferta(
        oportunidad_id=op.id, tipo="compra_energia",
        planta_nombre="GD Las Margaritas 1",
        municipio="Sincelejo", departamento="Sucre",
        operador_red_id=orr.id, energia_promedio_kwh_mes=185000)
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio == "Sincelejo"
    assert of.departamento == "Sucre"
    assert of.operador_red_id == orr.id
    assert float(of.energia_promedio_kwh_mes) == 185000.0


def test_los_cuatro_campos_son_opcionales(db):
    """Una oferta recién creada no sabe nada de la planta todavía."""
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia")
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio is None and of.departamento is None
    assert of.operador_red_id is None and of.energia_promedio_kwh_mes is None


# ── Task 2: la cascada Proyecto → oferta → null ──────────────────────────────

from app.services.comercial import ficha_operativa, meses_de_contrato  # noqa: E402


def _oferta(**kw):
    """Oferta mínima para la lógica pura: sin BD, solo los atributos que lee."""
    base = dict(planta_nombre=None, municipio=None, departamento=None,
                operador_red_id=None, energia_promedio_kwh_mes=None,
                fecha_tentativa_inicio=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _proyecto(**kw):
    base = dict(nombre_comercial=None, municipio=None, departamento=None,
                operador_red_id=None, operador_red_legal=None,
                mwh_mes_estimado=None, p50_mensual_kwh=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_sin_proyecto_la_ficha_sale_de_lo_declarado_en_la_oferta():
    """El caso GD Rio Pamplonita: la planta no existe como Proyecto y aun así el
    equipo tiene que poder consultar su lugar por API."""
    f = ficha_operativa(
        _oferta(planta_nombre="GD Rio Pamplonita", municipio="Cúcuta",
                departamento="Norte de Santander", operador_red_id=7),
        operador_oferta="CENS S.A. E.S.P.")

    assert f["proyecto_nombre"] == "GD Rio Pamplonita"
    assert f["municipio"] == "Cúcuta" and f["departamento"] == "Norte de Santander"
    assert f["operador_red"] == "CENS S.A. E.S.P." and f["operador_red_id"] == 7
    assert f["fuentes"]["municipio"] == "oferta"
    assert f["fuentes"]["operador_red"] == "oferta"


def test_el_proyecto_manda_sobre_lo_declarado():
    """Cuando la planta ya existe, el Proyecto es la verdad: lo declarado en la
    oferta fue una foto del momento de la venta y puede haber envejecido."""
    f = ficha_operativa(
        _oferta(planta_nombre="Catedral (borrador)", municipio="Sincelejo"),
        proyecto=_proyecto(nombre_comercial="GD Catedral", municipio="Corozal",
                           operador_red_legal="AFINIA S.A.S. E.S.P.", operador_red_id=3))

    assert f["proyecto_nombre"] == "GD Catedral"
    assert f["municipio"] == "Corozal"
    assert f["operador_red"] == "AFINIA S.A.S. E.S.P." and f["operador_red_id"] == 3
    assert f["fuentes"]["municipio"] == "proyecto"


def test_la_cascada_es_por_campo_no_por_entidad():
    """Un Proyecto a medio diligenciar no debe borrar lo que la oferta sí sabe."""
    f = ficha_operativa(
        _oferta(municipio="Sincelejo", departamento="Sucre"),
        proyecto=_proyecto(nombre_comercial="GD Catedral", municipio="Corozal"))

    assert f["municipio"] == "Corozal" and f["fuentes"]["municipio"] == "proyecto"
    assert f["departamento"] == "Sucre" and f["fuentes"]["departamento"] == "oferta"


def test_energia_promedio_del_proyecto_se_convierte_de_mwh_a_kwh():
    """`proyectos.mwh_mes_estimado` está en MWh; el CRM habla en kWh."""
    f = ficha_operativa(_oferta(), proyecto=_proyecto(mwh_mes_estimado=185.5))
    assert f["energia_promedio_kwh_mes"] == 185500.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "proyecto"


def test_sin_estimado_la_energia_promedio_cae_al_p50():
    """p50_mensual_kwh son 12 valores mensuales en kWh: el promedio es su media."""
    f = ficha_operativa(_oferta(), proyecto=_proyecto(p50_mensual_kwh=[100.0] * 11 + [220.0]))
    assert f["energia_promedio_kwh_mes"] == 110.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "proyecto"


def test_el_p50_guardado_como_texto_json_tambien_sirve():
    """Plantas viejas (Baraya, La Cumbia) tienen el p50 guardado como STRING JSON
    dentro del JSONB, no como arreglo: son datos anteriores a la migración a
    JSONB. Recorrer ese string da caracteres y `float('[')` reventaba la lista
    entera de /comercial/ofertas con un 500."""
    f = ficha_operativa(_oferta(),
                        proyecto=_proyecto(p50_mensual_kwh="[100.0, 100.0, 220.0]"))
    assert f["energia_promedio_kwh_mes"] == 140.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "proyecto"


def test_un_p50_ilegible_no_tumba_la_ficha():
    """Si el dato no se puede leer, la ficha cae al escalón siguiente de la
    cascada (lo declarado en la oferta). Nunca revienta."""
    f = ficha_operativa(_oferta(energia_promedio_kwh_mes=170000),
                        proyecto=_proyecto(p50_mensual_kwh="no es json"))
    assert f["energia_promedio_kwh_mes"] == 170000.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "oferta"


def test_sin_proyecto_la_energia_promedio_es_la_declarada():
    f = ficha_operativa(_oferta(energia_promedio_kwh_mes=170000))
    assert f["energia_promedio_kwh_mes"] == 170000.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "oferta"


def test_la_fecha_de_inicio_de_operacion_es_la_del_contrato():
    """Decisión de Juan: es el inicio de suministro del PPA, no la entrada en
    operación de la planta ni el inicio de comercialización."""
    ppa = types.SimpleNamespace(fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    f = ficha_operativa(_oferta(fecha_tentativa_inicio=dt.date(2026, 1, 1)), ppa=ppa)

    assert f["fecha_inicio_operacion"] == dt.date(2026, 2, 12)
    assert f["fuentes"]["fecha_inicio_operacion"] == "contrato"


def test_sin_contrato_la_fecha_es_la_tentativa_y_se_marca_estimada():
    """Una oferta no firmada no tiene PPA. La tentativa sirve, pero el consumidor
    de la API tiene que poder saber que es una estimación."""
    f = ficha_operativa(_oferta(fecha_tentativa_inicio=dt.date(2026, 10, 1)))
    assert f["fecha_inicio_operacion"] == dt.date(2026, 10, 1)
    assert f["fuentes"]["fecha_inicio_operacion"] == "estimada"
    assert f["contrato_compra_meses"] is None and f["contrato_compra_anios"] is None


def test_duracion_del_contrato_en_meses_calendario():
    """Se cuenta por mes calendario y no por días porque el PPA se factura por
    mes: es el mismo conteo que produce /firmar al expandir ppa_tarifas."""
    assert meses_de_contrato(dt.date(2026, 1, 1), dt.date(2026, 3, 31)) == 3      # Agustín 1
    assert meses_de_contrato(dt.date(2025, 11, 20), dt.date(2026, 12, 31)) == 14  # Bayunca
    assert meses_de_contrato(dt.date(2026, 2, 12), dt.date(2032, 12, 31)) == 83   # Catedral
    assert meses_de_contrato(dt.date(2026, 10, 1), dt.date(2036, 12, 31)) == 123
    assert meses_de_contrato(None, dt.date(2026, 3, 31)) is None
    assert meses_de_contrato(dt.date(2026, 3, 31), dt.date(2026, 1, 1)) is None


def test_la_duracion_tambien_viaja_en_anios():
    ppa = types.SimpleNamespace(fecha_inicio=dt.date(2026, 10, 1), fecha_fin=dt.date(2036, 12, 31))
    f = ficha_operativa(_oferta(), ppa=ppa)
    assert f["contrato_compra_meses"] == 123
    assert f["contrato_compra_anios"] == 10.3   # 10.25 redondeado hacia arriba
    assert f["contrato_fecha_inicio"] == dt.date(2026, 10, 1)
    assert f["contrato_fecha_fin"] == dt.date(2036, 12, 31)


def test_la_energia_real_viaja_con_su_periodo():
    """Sin el periodo, nadie sabe contra qué mes está comparando."""
    f = ficha_operativa(_oferta(), generacion=("2026-07", 182350.5))
    assert f["energia_real_kwh_mes"] == 182350.5
    assert f["energia_real_periodo"] == "2026-07"
    assert f["fuentes"]["energia_real_kwh_mes"] == "generacion"


def test_una_oferta_vacia_devuelve_nulls_y_fuentes_en_null():
    """"Todavía no lo sabemos" y "no aplica" tienen que verse distinto: el valor
    es null en ambos casos, pero `fuentes` dice que nadie lo aportó."""
    f = ficha_operativa(_oferta())
    for campo in ("proyecto_nombre", "municipio", "departamento", "operador_red",
                  "energia_promedio_kwh_mes", "energia_real_kwh_mes",
                  "fecha_inicio_operacion", "contrato_compra_meses"):
        assert f[campo] is None, campo
        assert f["fuentes"][campo] is None, campo


# ── Task 3: precarga por lotes ───────────────────────────────────────────────

from app.services.comercial import contexto_ficha  # noqa: E402


def _cliente_con_oferta(db, nombre="PELLETCO S.A.S.", **kw_oferta):
    cli = Cliente(razon_social_nombre=nombre)
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia", **kw_oferta)
    db.add(of); db.flush()
    return op, of


def _generacion(db, proyecto_id, anio, mes, dias, kwh_dia=1000):
    for d in range(1, dias + 1):
        db.add(GeneracionDiaria(proyecto_id=proyecto_id, fecha=dt.date(anio, mes, d),
                                kwh_real=kwh_dia))
    db.flush()


def test_el_contexto_trae_proyecto_ppa_y_operador_declarado(db):
    orr = OperadorRed(nombre_legal="CENS S.A. E.S.P.")
    db.add(orr); db.flush()
    proy = Proyecto(nombre_comercial="GD Catedral", municipio="Corozal")
    db.add(proy); db.flush()
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    db.add(ppa); db.flush()
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id,
                                operador_red_id=orr.id)
    db.commit()

    ctx = contexto_ficha(db, [of])
    assert ctx[of.id]["proyecto"].id == proy.id
    assert ctx[of.id]["ppa"].id == ppa.id
    assert ctx[of.id]["operador_oferta"] == "CENS S.A. E.S.P."
    assert ctx[of.id]["generacion"] is None   # la planta no ha generado


def test_la_energia_real_es_la_del_ultimo_mes_cerrado(db):
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 6, 30, kwh_dia=900)
    _generacion(db, proy.id, 2026, 7, 31, kwh_dia=1000)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    ctx = contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))
    assert ctx[of.id]["generacion"] == ("2026-07", 31000.0)


def test_el_mes_en_curso_no_cuenta(db):
    """Tres días de agosto no son la energía del mes."""
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 8, 3)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    assert contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))[of.id]["generacion"] is None


def test_un_mes_con_lecturas_a_medias_tampoco_cuenta(db):
    """20 de 31 días reportados darían un número 35% bajo, presentado como real."""
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 7, 20)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    assert contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))[of.id]["generacion"] is None


def test_lo_borrado_no_alimenta_la_ficha(db):
    """Un contrato o un proyecto con deleted_at ya no son la verdad de nadie."""
    proy = Proyecto(nombre_comercial="Planta borrada",
                    deleted_at=dt.datetime(2026, 7, 1))
    db.add(proy); db.flush()
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2030, 12, 31),
                      deleted_at=dt.datetime(2026, 7, 1))
    db.add(ppa); db.flush()
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id)
    db.commit()

    ctx = contexto_ficha(db, [of])
    assert ctx[of.id]["proyecto"] is None and ctx[of.id]["ppa"] is None


def test_sin_ofertas_el_contexto_es_vacio(db):
    assert contexto_ficha(db, []) == {}


def test_una_oferta_sin_nada_enlazado_no_rompe(db):
    _, of = _cliente_con_oferta(db, planta_nombre="GD Rio Pamplonita")
    db.commit()
    ctx = contexto_ficha(db, [of])
    assert ctx[of.id] == {"proyecto": None, "ppa": None, "generacion": None,
                          "operador_oferta": None}


# ── Task 4: la ficha viaja por la API ────────────────────────────────────────

from fastapi import HTTPException  # noqa: E402

from app.api.v1 import comercial as api  # noqa: E402
from app.schemas.comercial import (  # noqa: E402
    FirmarOfertaIn, OfertaCreate, OfertaUpdate, OportunidadCreate,
)


def _listar(db):
    """Los filtros van explícitos: llamando el endpoint directo, los defaults
    Query(None) de FastAPI llegarían como objetos Query, no como None."""
    return api.list_ofertas_todas(tipo=None, estado=None, resultado=None, q=None,
                                  solo_alerta=False, db=db, current=ADMIN)


def test_la_ficha_viaja_en_la_lista_plana_de_ofertas(db):
    """La lista plana es la fuente de la vista principal de /comercial y es la
    que el equipo va a consumir por API."""
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Las Margaritas 1",
        municipio="Sincelejo", departamento="Sucre", operador_red_id=orr.id,
        energia_promedio_kwh_mes=185000,
        fecha_tentativa_inicio=dt.date(2026, 10, 1)), db=db, current=ADMIN)

    fila = _listar(db)[0]
    ficha = fila["ficha"]
    assert ficha["proyecto_nombre"] == "GD Las Margaritas 1"
    assert ficha["municipio"] == "Sincelejo"
    assert ficha["operador_red"] == "AFINIA S.A.S. E.S.P."
    assert ficha["energia_promedio_kwh_mes"] == 185000.0
    assert ficha["fecha_inicio_operacion"] == dt.date(2026, 10, 1)
    assert ficha["fuentes"]["fecha_inicio_operacion"] == "estimada"
    # y lo declarado en crudo, para que el editor sepa qué es suyo
    assert fila["municipio"] == "Sincelejo" and fila["operador_red_id"] == orr.id


def test_la_ficha_viaja_en_el_detalle_de_la_oportunidad(db):
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="Agustín 1", municipio="Sabanalarga"),
        db=db, current=ADMIN)

    detalle = api.get_oportunidad(op["id"], db=db, current=ADMIN)
    assert detalle["ofertas"][0]["ficha"]["municipio"] == "Sabanalarga"
    assert detalle["ofertas"][0]["ficha"]["fuentes"]["municipio"] == "oferta"


def test_la_ficha_de_una_oferta_firmada_toma_la_fecha_y_la_duracion_del_ppa(db):
    cli = Cliente(razon_social_nombre="PELLETCO S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    of = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="Catedral"), db=db, current=ADMIN)
    api.firmar_oferta(of["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31),
        tarifa_base=308), db=db, current=ADMIN)

    ficha = _listar(db)[0]["ficha"]
    assert ficha["fecha_inicio_operacion"] == dt.date(2026, 2, 12)
    assert ficha["fuentes"]["fecha_inicio_operacion"] == "contrato"
    assert ficha["contrato_compra_meses"] == 83
    assert ficha["contrato_compra_anios"] == 6.9


def test_el_patch_escribe_los_campos_declarados(db):
    """Si no son editables, el equipo no puede llenarlos nunca."""
    orr = OperadorRed(nombre_legal="ESSA S.A. E.S.P.")
    db.add(orr); db.flush()
    cli = Cliente(razon_social_nombre="RECURSOS AGROPECUARIOS S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    of = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Rio Pamplonita"), db=db, current=ADMIN)

    api.update_oferta(of["id"], OfertaUpdate(
        municipio="Cúcuta", departamento="Norte de Santander",
        operador_red_id=orr.id, energia_promedio_kwh_mes=95000),
        db=db, current=ADMIN)

    ficha = _listar(db)[0]["ficha"]
    assert ficha["municipio"] == "Cúcuta"
    assert ficha["operador_red"] == "ESSA S.A. E.S.P."
    assert ficha["energia_promedio_kwh_mes"] == 95000.0


def test_un_operador_de_red_inexistente_da_422(db):
    """Sin esto sería un IntegrityError 500 en producción."""
    cli = Cliente(razon_social_nombre="SONETEL S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)

    with pytest.raises(HTTPException) as e:
        api.create_oferta(op["id"], OfertaCreate(
            tipo="compra_energia", operador_red_id=9999), db=db, current=ADMIN)
    assert e.value.status_code == 422


def test_toda_lectura_de_una_oferta_trae_su_ficha(db):
    """La forma de la respuesta no puede depender del endpoint: si un consumidor
    lee ficha.municipio en la lista, tiene que poder leerlo en cualquier otra
    respuesta que devuelva una oferta."""
    cli = Cliente(razon_social_nombre="SAMBA SOLAR S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    creada = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="San Pelayo", municipio="Sincelejo"),
        db=db, current=ADMIN)

    respuestas = {
        "create": creada,
        "lista_plana": _listar(db)[0],
        "lista_del_cliente": api.list_ofertas(op["id"], db=db, current=ADMIN)[0],
        "detalle": api.get_oportunidad(op["id"], db=db, current=ADMIN)["ofertas"][0],
        "seguimiento": api.registrar_seguimiento(creada["id"], db=db, current=ADMIN),
    }
    for donde, r in respuestas.items():
        assert r["ficha"] is not None, f"{donde} no trae ficha"
        assert r["ficha"]["municipio"] == "Sincelejo", donde


def _oferta_completa(db, op_id, i):
    """Una oferta con proyecto, contrato y generación propios."""
    proy = Proyecto(nombre_comercial=f"Planta {i}", municipio="Corozal",
                    mwh_mes_estimado=100 + i)
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 7, 31)
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2030, 12, 31))
    db.add(ppa); db.flush()
    of = OportunidadOferta(oportunidad_id=op_id, tipo="compra_energia",
                           planta_nombre=f"Planta {i}", proyecto_id=proy.id,
                           ppa_contrato_id=ppa.id)
    db.add(of); db.commit()


def test_la_lista_no_hace_una_consulta_por_oferta(db):
    """La vista principal carga TODAS las ofertas de una: si la ficha costara una
    consulta por fila, esto se caería con el volumen real."""
    cli = Cliente(razon_social_nombre="GRUPO CON MUCHAS PLANTAS S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.commit()
    for i in range(2):
        _oferta_completa(db, op.id, i)

    consultas = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*args, **kwargs):
        consultas["n"] += 1

    _listar(db)
    con_dos = consultas["n"]

    for i in range(2, 8):
        _oferta_completa(db, op.id, i)
    consultas["n"] = 0
    filas = _listar(db)
    con_ocho = consultas["n"]   # leerlo ANTES de cualquier otra llamada

    assert len(filas) == 8
    assert con_ocho == con_dos, (
        f"{con_dos} consultas con 2 ofertas y {con_ocho} con 8: hay N+1")
