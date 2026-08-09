"""Aplicador del archivo de actualizacion del CRM comercial. La union con la
base es SIEMPRE por (consecutivo, mes, anio) del codigo — nunca por nombre, y
nunca difusa."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.comercial import Oportunidad, OportunidadGestion, OportunidadOferta
from app.services.comercial_actualizacion import aplicar, indexar_por_codigo


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    _sembrar(s)
    yield s
    s.close()


def _sembrar(db):
    c = Cliente(razon_social_nombre="ENEXA ENERGY S.A.S.")
    otro = Cliente(razon_social_nombre="ECOSUN")
    db.add_all([c, otro])
    db.flush()
    hace_rato = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)
    op = Oportunidad(cliente_id=c.id, estado="oportunidad", estado_desde=hace_rato)
    op2 = Oportunidad(cliente_id=otro.id, estado="oportunidad", estado_desde=hace_rato)
    db.add_all([op, op2])
    db.flush()
    # Prefijo OF. a proposito: en produccion es OP. y debe dar igual.
    db.add(OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia",
                             numero_oferta="OF.COM No.0103-6-2026",
                             estado="oportunidad", estado_desde=hace_rato))
    db.add(OportunidadOferta(oportunidad_id=op.id, tipo="servicios_operacionales",
                             numero_oferta="OP.REPCGM No.0153-06-2027",
                             estado="oportunidad", estado_desde=hace_rato))
    db.add(OportunidadOferta(oportunidad_id=op2.id, tipo="servicios_operacionales",
                             numero_oferta="OP.REPCGM No.0157-06-2026",
                             estado="oportunidad", estado_desde=hace_rato))
    db.commit()


# ── indice y envios ──────────────────────────────────────────────────────────

def test_indexa_ignorando_el_prefijo(db):
    idx = indexar_por_codigo(db)
    assert (103, 6, 2026) in idx and (153, 6, 2027) in idx


def test_envios_rellena_los_tres_campos(db):
    datos = {"envios": [{"codigo": "No.0103-6-2026", "planta_nombre": "Barisol I",
                         "fecha_oferta": "2026-06-22", "seguimientos": 2,
                         "fecha_ultima_respuesta": None,
                         "documento_url": "https://drive.google.com/x"}]}
    rep = aplicar(db, datos, dry_run=False)
    o = indexar_por_codigo(db)[(103, 6, 2026)]
    assert rep["envios"] == 1
    assert (o.fecha_oferta.isoformat(), o.seguimientos, o.planta_nombre) == \
        ("2026-06-22", 2, "Barisol I")
    assert o.documento_url == "https://drive.google.com/x"


def test_dry_run_no_escribe(db):
    datos = {"envios": [{"codigo": "No.0103-6-2026", "fecha_oferta": "2026-06-22",
                         "seguimientos": 2}]}
    rep = aplicar(db, datos, dry_run=True)
    assert rep["envios"] == 1
    assert indexar_por_codigo(db)[(103, 6, 2026)].seguimientos == 0


def test_codigo_inexistente_se_reporta_y_no_revienta(db):
    rep = aplicar(db, {"envios": [{"codigo": "No.9999-1-2026", "seguimientos": 1}]},
                  dry_run=False)
    assert rep["envios"] == 0 and "No.9999-1-2026" in rep["no_encontrados"]


def test_correccion_de_anio_reescribe_el_codigo(db):
    datos = {"correcciones": [{"codigo_actual": "No.0153-06-2027",
                               "codigo_nuevo": "OP.REPCGM No.0153-06-2026"}]}
    rep = aplicar(db, datos, dry_run=False)
    assert rep["correcciones"] == 1 and (153, 6, 2026) in indexar_por_codigo(db)


def test_planta_existente_no_se_pisa(db):
    o = indexar_por_codigo(db)[(103, 6, 2026)]
    o.planta_nombre = "Nombre puesto a mano"
    db.commit()
    aplicar(db, {"envios": [{"codigo": "No.0103-6-2026", "planta_nombre": "Barisol I"}]},
            dry_run=False)
    db.refresh(o)
    assert o.planta_nombre == "Nombre puesto a mano"


def test_es_idempotente(db):
    datos = {"envios": [{"codigo": "No.0103-6-2026", "seguimientos": 2,
                         "fecha_oferta": "2026-06-22"}]}
    aplicar(db, datos, dry_run=False)
    aplicar(db, datos, dry_run=False)
    assert indexar_por_codigo(db)[(103, 6, 2026)].seguimientos == 2


# ── estados y bitacora ───────────────────────────────────────────────────────

def test_estado_mueve_la_oferta_y_deja_gestion(db):
    datos = {"estados": [{"codigo": "No.0103-6-2026",
                          "estado_oportunidad": "declinado",
                          "resultado_oferta": "declinado",
                          "gestion": "Se fueron con otro comercializador."}]}
    rep = aplicar(db, datos, dry_run=False)
    o = indexar_por_codigo(db)[(103, 6, 2026)]
    assert rep["estados"] == 1
    assert o.estado == "declinado" and o.resultado == "declinado"
    g = db.query(OportunidadGestion).all()
    assert len(g) == 1 and "otro comercializador" in g[0].descripcion


def test_solo_mueve_la_oferta_nombrada_no_sus_hermanas(db):
    """El punto de mudar la etapa a la oferta: 0103 se declina y la 0153 del
    mismo cliente sigue viva."""
    aplicar(db, {"estados": [{"codigo": "No.0103-6-2026",
                              "estado_oportunidad": "declinado",
                              "resultado_oferta": "declinado",
                              "gestion": "Se cayo."}]}, dry_run=False)
    idx = indexar_por_codigo(db)
    assert idx[(103, 6, 2026)].estado == "declinado"
    assert idx[(153, 6, 2027)].estado == "oportunidad"


def test_estado_actualiza_estado_desde_para_reiniciar_la_alerta(db):
    previo = indexar_por_codigo(db)[(103, 6, 2026)].estado_desde
    aplicar(db, {"estados": [{"codigo": "No.0103-6-2026",
                              "estado_oportunidad": "envio_oferta",
                              "gestion": "Vigente."}]}, dry_run=False)
    assert indexar_por_codigo(db)[(103, 6, 2026)].estado_desde > previo


def test_no_duplica_la_gestion_al_reaplicar(db):
    datos = {"estados": [{"codigo": "No.0103-6-2026", "estado_oportunidad": "declinado",
                          "gestion": "Se cayo."}]}
    aplicar(db, datos, dry_run=False)
    aplicar(db, datos, dry_run=False)
    assert db.query(OportunidadGestion).count() == 1


def test_estado_sin_resultado_no_toca_la_oferta(db):
    """El caso Terpel: queda la nota en bitacora, sin mover el resultado."""
    aplicar(db, {"estados": [{"codigo": "No.0103-6-2026",
                              "estado_oportunidad": "envio_oferta",
                              "gestion": "A cargo de Edu."}]}, dry_run=False)
    assert indexar_por_codigo(db)[(103, 6, 2026)].resultado == "pendiente"


# ── ofertas nuevas, borrado y fusiones ───────────────────────────────────────

def test_crea_oferta_nueva_en_el_cliente_correcto(db):
    datos = {"ofertas_nuevas": [{"cliente": "ENEXA ENERGY S.A.S.",
                                 "tipo": "compra_energia",
                                 "codigo": "OP.COM No.0118-7-2026",
                                 "planta_nombre": "GD La Maria",
                                 "fecha_oferta": "2026-07-14",
                                 "seguimientos": 1}]}
    rep = aplicar(db, datos, dry_run=False)
    o = indexar_por_codigo(db)[(118, 7, 2026)]
    assert rep["creadas"] == 1
    assert o.planta_nombre == "GD La Maria" and o.seguimientos == 1


def test_no_recrea_una_oferta_que_ya_existe(db):
    datos = {"ofertas_nuevas": [{"cliente": "ENEXA ENERGY S.A.S.",
                                 "tipo": "compra_energia",
                                 "codigo": "OP.COM No.0103-6-2026"}]}
    assert aplicar(db, datos, dry_run=False)["creadas"] == 0


def test_cliente_inexistente_se_reporta_sin_crear_nada(db):
    rep = aplicar(db, {"ofertas_nuevas": [{"cliente": "NO EXISTE SAS",
                                           "tipo": "compra_energia",
                                           "codigo": "OP.COM No.0500-7-2026"}]},
                  dry_run=False)
    assert rep["creadas"] == 0
    assert any("NO EXISTE SAS" in s for s in rep["sin_resolver"])


def test_eliminar_borra_la_oferta_y_deja_su_huella(db):
    rep = aplicar(db, {"eliminar": [{"codigo": "No.0103-6-2026", "motivo": "fila basura"}]},
                  dry_run=False)
    assert rep["eliminadas"] == 1 and (103, 6, 2026) not in indexar_por_codigo(db)
    # El borrado es irreversible: la fila completa queda en el reporte.
    assert rep["borradas_detalle"][0]["numero_oferta"] == "OF.COM No.0103-6-2026"


def test_eliminar_en_dry_run_no_borra(db):
    aplicar(db, {"eliminar": [{"codigo": "No.0103-6-2026", "motivo": "x"}]}, dry_run=True)
    assert (103, 6, 2026) in indexar_por_codigo(db)


def test_fusion_mueve_las_ofertas_y_da_de_baja_al_perdedor(db):
    rep = aplicar(db, {"fusionar_clientes": [
        {"ganador": "ENEXA ENERGY S.A.S.", "perdedor": "ECOSUN"}]}, dry_run=False)
    assert rep["fusiones"] == 1
    ganador = next(c for c in db.query(Cliente).all()
                   if c.razon_social_nombre == "ENEXA ENERGY S.A.S.")
    perdedor = next(c for c in db.query(Cliente).all()
                    if c.razon_social_nombre == "ECOSUN")
    movida = indexar_por_codigo(db)[(157, 6, 2026)]
    assert movida.oportunidad.cliente_id == ganador.id
    assert perdedor.deleted_at is not None


# ── fidelidad del dry-run ────────────────────────────────────────────────────
# El reporte en seco es lo que se usa para decidir si aplicar. Si da falsas
# alarmas no sirve: estos dos casos las producian.

def test_dry_run_resuelve_estados_que_dependen_de_una_correccion(db):
    """El estado apunta al codigo YA corregido; en seco la correccion no se
    escribe, pero el reporte debe verlo igual que en la corrida real."""
    datos = {
        "correcciones": [{"codigo_actual": "No.0153-06-2027",
                          "codigo_nuevo": "OP.REPCGM No.0153-06-2026"}],
        "estados": [{"codigo": "No.0153-06-2026", "estado_oportunidad": "envio_oferta",
                     "gestion": "Tauramena pendiente."}],
    }
    seco = aplicar(db, datos, dry_run=True)
    assert seco["estados"] == 1 and not seco["no_encontrados"]
    real = aplicar(db, datos, dry_run=False)
    assert real["estados"] == seco["estados"]


def test_dry_run_cuenta_ofertas_de_un_cliente_creado_en_la_misma_corrida(db):
    datos = {
        "clientes_nuevos": [{"razon_social_nombre": "FOCUSING S.A.S."}],
        "ofertas_nuevas": [{"cliente": "FOCUSING S.A.S.", "tipo": "compra_energia",
                            "codigo": "OP.COM No.0118-7-2026"}],
    }
    seco = aplicar(db, datos, dry_run=True)
    assert seco["creadas"] == 1 and not seco["sin_resolver"]
    real = aplicar(db, datos, dry_run=False)
    assert (real["creadas"], real["clientes_creados"]) == (1, 1)


def test_crea_cliente_nuevo_y_su_oferta_en_la_misma_corrida(db):
    """Focusing (GD La Maria) no existia: se crea y su oferta cuelga de el."""
    datos = {
        "clientes_nuevos": [{"razon_social_nombre": "FOCUSING S.A.S.",
                             "origen_tipo": "prospeccion"}],
        "ofertas_nuevas": [{"cliente": "FOCUSING S.A.S.", "tipo": "compra_energia",
                            "codigo": "OP.COM No.0118-7-2026",
                            "planta_nombre": "GD La Maria",
                            "fecha_oferta": "2026-07-14"}],
    }
    rep = aplicar(db, datos, dry_run=False)
    assert rep["clientes_creados"] == 1 and rep["creadas"] == 1
    o = indexar_por_codigo(db)[(118, 7, 2026)]
    assert o.oportunidad.cliente.razon_social_nombre == "FOCUSING S.A.S."


def test_no_duplica_un_cliente_que_ya_existe(db):
    datos = {"clientes_nuevos": [{"razon_social_nombre": "ECOSUN"}]}
    assert aplicar(db, datos, dry_run=False)["clientes_creados"] == 0


def test_fusion_con_cliente_inexistente_se_reporta(db):
    rep = aplicar(db, {"fusionar_clientes": [
        {"ganador": "NO EXISTE", "perdedor": "ECOSUN"}]}, dry_run=False)
    assert rep["fusiones"] == 0 and rep["sin_resolver"]
