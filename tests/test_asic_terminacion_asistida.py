"""POST /asic/terminacion — terminar heredando la identidad del contrato.

Antes, el formulario guardaba la terminación con SIC, fecha y cédulas y nada
más: sin contrato interno ni nombre interno. Salía en blanco en la tabla y en
el Excel, y no había forma de saber a qué contrato pertenecía sin cruzar el SIC
a mano.

Lo que NO cambia y estas pruebas blindan: la terminación se sigue guardando
SIN `proyecto_id`. Con planta, `resolver_vigencias` la saca de las activas y
Cumplimiento la borra del mes de la terminación en vez de prorratearla hasta la
fecha.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.cumplimiento import CumplimientoMensual
from app.models.asic import AsicCambioContrato, TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.schemas.asic import AsicTerminacionCreate
from app.api.v1 import asic as asic_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    """El endpoint inserta sin `id` (en Postgres lo pone la secuencia). SQLite
    solo autoincrementa un PK declarado INTEGER, no BIGINT."""
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, AsicSolicitud.__table__, AsicCambioContrato.__table__,
            PPAContrato.__table__, CumplimientoMensual.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _planta(db, nombre):
    p = Proyecto(id=next(_ids), nombre_comercial=nombre)
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("reemplaza_anterior", True)
    # Los server_default booleanos ("false") vuelven como texto bajo SQLite y
    # evalúan a True; en Postgres son booleanos de verdad.
    kw.setdefault("es_duplicado", False)
    kw.setdefault("uso_del_recurso", False)
    s = AsicSolicitud(id=next(_ids), **kw)
    db.add(s)
    return s


def _registro(db, **overrides):
    planta = _planta(db, overrides.pop("planta", "MGS 0031 Marimonda"))
    campos = dict(
        proyecto_id=planta.id,
        tipo_solicitud=TipoSolicitudAsicEnum.registro,
        codigo_sic_contrato="88806",
        codigo_sic_vendedor="UNGG",
        codigo_sic_comprador="BIAC",
        cedula_agente_vendedor="1037625350",
        cedula_agente_comprador="1107047209",
        contrato_interno="UNERGY 001-2024",
        nombre_interno="Terpel 1",
        prioridad_limitacion=83,
        tipo_mercado="No regulado",
        tipo_asignacion="Prorrata",
        porcentaje_fncer=100,
        porcentaje_despacho=0.9,
        requerimiento_asic="20240419001",
        fecha_inicio=date(2024, 5, 1),
        fecha_fin=date(2030, 12, 31),
    )
    campos.update(overrides)
    s = _sol(db, **campos)
    db.commit()
    return planta, s


def _payload(**kw):
    base = dict(
        codigo_sic_contrato="88806",
        fecha_terminacion=date(2026, 9, 30),
        requerimiento_asic="20260930001",
    )
    base.update(kw)
    return AsicTerminacionCreate(**base)


def _crear(db, **kw):
    return asic_api.create_terminacion(data=_payload(**kw), db=db, _=None)


def _fila(db, id_):
    return db.query(AsicSolicitud).filter(AsicSolicitud.id == id_).first()


# ── Lo que el usuario pidió: que la identidad quede guardada ──────────────

def test_la_terminacion_guarda_la_identidad_del_contrato(db):
    _registro(db)

    out = _crear(db)

    t = _fila(db, out.terminacion.id)
    assert t.tipo_solicitud == TipoSolicitudAsicEnum.terminacion
    assert t.codigo_sic_contrato == "88806"
    assert t.contrato_interno == "UNERGY 001-2024"
    assert t.nombre_interno == "Terpel 1"
    assert t.codigo_sic_vendedor == "UNGG"
    assert t.codigo_sic_comprador == "BIAC"
    assert t.prioridad_limitacion == 83
    assert t.tipo_mercado == "No regulado"
    assert t.tipo_asignacion == "Prorrata"
    assert t.fecha_fin == date(2026, 9, 30)


def test_hereda_el_ppa_del_registro(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1")
    db.add(ppa)
    db.flush()
    _registro(db, contrato_ppa_id=ppa.id)

    out = _crear(db)

    assert _fila(db, out.terminacion.id).contrato_ppa_id == ppa.id


def test_las_cedulas_se_heredan_si_no_se_dan(db):
    _registro(db)

    out = _crear(db)
    t = _fila(db, out.terminacion.id)
    assert t.cedula_agente_vendedor == "1037625350"
    assert t.cedula_agente_comprador == "1107047209"


def test_las_cedulas_dadas_ganan_a_las_heredadas(db):
    _registro(db)

    out = _crear(db, cedula_agente_vendedor="999", cedula_agente_comprador="888")
    t = _fila(db, out.terminacion.id)
    assert t.cedula_agente_vendedor == "999"
    assert t.cedula_agente_comprador == "888"


# ── Lo que NO debe cambiar ────────────────────────────────────────────────

def test_la_terminacion_no_guarda_planta(db):
    """Con proyecto_id, Cumplimiento borra la planta del mes de la terminación
    en vez de prorratearla hasta la fecha."""
    _registro(db)

    out = _crear(db)

    assert _fila(db, out.terminacion.id).proyecto_id is None
    # Pero la planta se muestra igual, derivada del SIC (display-only)
    assert out.terminacion.planta_nombre == "MGS 0031 Marimonda"


def test_no_hereda_los_porcentajes(db):
    """Una terminación no aporta energía: %FNCER y %despacho serían ruido."""
    _registro(db)

    out = _crear(db)

    t = _fila(db, out.terminacion.id)
    assert t.porcentaje_fncer is None
    assert t.porcentaje_despacho is None


def test_estampa_la_fecha_de_fin_en_los_registros_del_sic(db):
    _, registro = _registro(db)

    out = _crear(db)

    assert _fila(db, registro.id).fecha_fin == date(2026, 9, 30)
    assert [c.id for c in out.cerrados] == [registro.id]
    assert "MGS 0031 Marimonda" in out.resumen


def test_cierra_todas_las_plantas_del_sic(db):
    _, registro = _registro(db)
    otra = _planta(db, "MGS 0022 Yuan")
    coexistente = _sol(db, proyecto_id=otra.id, tipo_solicitud=TipoSolicitudAsicEnum.registro,
                       codigo_sic_contrato="88806", contrato_interno="UNERGY 001-2024",
                       nombre_interno="Terpel 1", requerimiento_asic="20240419002",
                       fecha_inicio=date(2024, 6, 1), fecha_fin=date(2030, 12, 31),
                       reemplaza_anterior=False)
    db.commit()

    out = _crear(db)

    assert _fila(db, registro.id).fecha_fin == date(2026, 9, 30)
    assert _fila(db, coexistente.id).fecha_fin == date(2026, 9, 30)
    assert len(out.cerrados) == 2


def test_no_recorta_un_registro_que_ya_terminaba_antes(db):
    _, registro = _registro(db, fecha_fin=date(2025, 6, 30))

    out = _crear(db)

    assert _fila(db, registro.id).fecha_fin == date(2025, 6, 30), "no se alarga"
    assert out.cerrados == []


def test_en_borrador_no_cierra_nada(db):
    _, registro = _registro(db)

    out = _crear(db, estado_solicitud="en_proceso")

    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)
    assert out.cerrados == []
    assert "borrador" in out.resumen


# ── Validaciones ──────────────────────────────────────────────────────────

def test_sic_inexistente_da_404(db):
    _registro(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, codigo_sic_contrato="00000")
    assert e.value.status_code == 404


def test_no_puede_terminar_antes_de_que_empiece(db):
    _registro(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, fecha_terminacion=date(2023, 1, 1))
    assert e.value.status_code == 422
    assert "01/05/2024" in e.value.detail


def test_el_requerimiento_no_puede_repetir_el_del_registro(db):
    _registro(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, requerimiento_asic="20240419001")
    assert e.value.status_code == 422


def test_el_requerimiento_es_opcional(db):
    _registro(db)
    out = _crear(db, requerimiento_asic=None)
    assert _fila(db, out.terminacion.id).requerimiento_asic is None


def test_no_puede_terminar_despues_del_fin_del_ppa(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1", fecha_fin=date(2030, 12, 31))
    db.add(ppa)
    db.flush()
    _, registro = _registro(db, contrato_ppa_id=ppa.id)
    antes = db.query(AsicSolicitud).count()

    with pytest.raises(HTTPException) as e:
        _crear(db, fecha_terminacion=date(2035, 1, 1))
    assert e.value.status_code == 422

    db.rollback()
    assert db.query(AsicSolicitud).count() == antes
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31), "no quedó estampada a medias"


# ── Borrado: las terminaciones quedan exentas del bloqueo por cumplimiento ─

def _con_cumplimiento(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1")
    db.add(ppa)
    db.flush()
    db.add(CumplimientoMensual(id=next(_ids), contrato_ppa_id=ppa.id, anio=2026, mes=7))
    _, registro = _registro(db, contrato_ppa_id=ppa.id)
    db.commit()
    return ppa, registro


def test_una_terminacion_se_puede_borrar_aunque_herede_el_contrato(db):
    _con_cumplimiento(db)
    out = _crear(db)

    asic_api.delete_solicitud(id=out.terminacion.id, db=db, _=None)

    assert _fila(db, out.terminacion.id) is None


def test_un_registro_sigue_protegido(db):
    """La exención es solo para terminaciones: un registro aporta energía al
    cálculo y no se puede borrar si el contrato ya tiene cumplimiento."""
    _, registro = _con_cumplimiento(db)

    with pytest.raises(HTTPException) as e:
        asic_api.delete_solicitud(id=registro.id, db=db, _=None)
    assert e.value.status_code == 409
    assert "cumplimiento" in e.value.detail


# ── Backfill de las terminaciones viejas ──────────────────────────────────

def test_backfill_completa_las_terminaciones_en_blanco(db):
    _, registro = _registro(db)
    vieja = _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                 codigo_sic_contrato="88806", fecha_fin=date(2026, 3, 31),
                 requerimiento_asic="20260301001")
    db.commit()

    previo = asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)
    assert previo["a_actualizar"] == 1
    assert previo["resueltos"][0]["cambios"]["contrato_interno"] == "UNERGY 001-2024"
    assert _fila(db, vieja.id).contrato_interno is None, "dry_run no toca nada"

    asic_api.backfill_terminaciones(dry_run=False, db=db, _=None)

    t = _fila(db, vieja.id)
    assert t.contrato_interno == "UNERGY 001-2024"
    assert t.nombre_interno == "Terpel 1"
    assert t.codigo_sic_vendedor == "UNGG"
    assert t.codigo_sic_comprador == "BIAC"
    assert t.prioridad_limitacion == 83
    assert t.proyecto_id is None, "el backfill NO le pone planta"


def test_backfill_es_idempotente_y_no_pisa_lo_que_ya_hay(db):
    _registro(db)
    vieja = _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                 codigo_sic_contrato="88806", fecha_fin=date(2026, 3, 31),
                 nombre_interno="Nombre puesto a mano")
    db.commit()

    asic_api.backfill_terminaciones(dry_run=False, db=db, _=None)
    t = _fila(db, vieja.id)
    assert t.nombre_interno == "Nombre puesto a mano"
    assert t.contrato_interno == "UNERGY 001-2024"

    segunda = asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)
    assert segunda["a_actualizar"] == 0


def test_backfill_estampa_las_fechas_que_quedaron_sin_recortar(db):
    """Caso La Paz Verso: la terminación existe pero el registro sigue diciendo
    2030 porque _auto_terminate nunca corrió sobre él (carga directa a BD, o un
    registro editado después)."""
    _, registro = _registro(db)
    termino = _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                   codigo_sic_contrato="88806", fecha_fin=date(2026, 8, 13),
                   requerimiento_asic="202608130012")
    db.commit()
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)

    previo = asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)
    assert previo["a_recortar"] == 1
    assert previo["sin_recortar"][0]["requerimiento_asic"] == "202608130012"
    assert previo["sin_recortar"][0]["registros"][0]["id"] == registro.id
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31), "dry_run no toca"

    asic_api.backfill_terminaciones(dry_run=False, db=db, _=None)

    assert _fila(db, registro.id).fecha_fin == date(2026, 8, 13)
    assert _fila(db, termino.id).fecha_fin == date(2026, 8, 13)
    assert asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)["a_recortar"] == 0


def test_backfill_no_recorta_por_una_terminacion_en_borrador(db):
    _, registro = _registro(db)
    _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         estado_solicitud=EstadoSolicitudAsicEnum.en_proceso,
         codigo_sic_contrato="88806", fecha_fin=date(2026, 8, 13))
    db.commit()

    assert asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)["a_recortar"] == 0
    asic_api.backfill_terminaciones(dry_run=False, db=db, _=None)
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)


def test_backfill_no_alarga_a_quien_ya_terminaba_antes(db):
    _, registro = _registro(db, fecha_fin=date(2025, 6, 30))
    _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         codigo_sic_contrato="88806", fecha_fin=date(2026, 8, 13))
    db.commit()

    assert asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)["a_recortar"] == 0
    asic_api.backfill_terminaciones(dry_run=False, db=db, _=None)
    assert _fila(db, registro.id).fecha_fin == date(2025, 6, 30)


def test_la_vigencia_efectiva_ya_sale_bien_sin_correr_el_backfill(db):
    """Lo que de verdad arregla el cálculo es que la terminación se resuelva
    sola: el backfill solo endereza la fecha ALMACENADA."""
    _, registro = _registro(db)
    _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         codigo_sic_contrato="88806", fecha_fin=date(2026, 8, 13))
    db.commit()

    outs = {o.id: o for o in asic_api.list_solicitudes(
        db=db, _=None, codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None)}
    assert outs[registro.id].fecha_fin_efectiva == date(2026, 8, 13)
    assert outs[registro.id].es_version_vigente is False
    assert outs[registro.id].fecha_fin == date(2030, 12, 31), "la cruda sigue intacta"


def test_backfill_reporta_las_que_no_puede_resolver(db):
    _sol(db, tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         codigo_sic_contrato="99999", fecha_fin=date(2026, 3, 31))
    db.commit()

    reporte = asic_api.backfill_terminaciones(dry_run=True, db=db, _=None)
    assert reporte["a_actualizar"] == 0
    assert reporte["sin_resolver"] == 1
    assert "99999" in reporte["no_resueltos"][0]["codigo_sic_contrato"]
