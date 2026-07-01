"""La planta de una terminación se muestra aunque no lleve proyecto_id.

Bug: una terminación se guarda con proyecto_id=NULL (por diseño, para no romper
Cumplimiento). El visual de GESCON resolvía la planta solo desde proyecto_id, así
que las filas terminadas mostraban "—". El fix deriva la planta del/los registro(s)
vigente(s) del mismo código SIC (display-only, sin tocar el dato almacenado).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1 import asic as asic_api


# JSONB es de Postgres; en SQLite (tests) lo renderizamos como TEXT.
@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    # Solo las tablas que toca el endpoint; el resto del metadata usa tipos PG.
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


# SQLite no autoincrementa PK BigInteger; asignamos ids explícitos.
_ids = iter(range(1, 10_000))


def _planta(db, nombre):
    p = Proyecto(id=next(_ids), nombre_comercial=nombre)
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    db.add(AsicSolicitud(id=next(_ids), **kw))


def test_terminacion_sin_proyecto_muestra_planta_via_sic(db):
    p = _planta(db, "Planta Sol del Norte")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="87552",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado)
    _sol(db, proyecto_id=None, codigo_sic_contrato="87552",
         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado)
    db.commit()

    outs = asic_api.list_solicitudes(codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None, db=db, _=None)
    term = next(o for o in outs if o.tipo_solicitud == TipoSolicitudAsicEnum.terminacion)
    assert term.planta_nombre == "Planta Sol del Norte"


def test_terminacion_sin_registro_hermano_queda_sin_planta(db):
    _sol(db, proyecto_id=None, codigo_sic_contrato="99999",
         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado)
    db.commit()
    outs = asic_api.list_solicitudes(codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None, db=db, _=None)
    assert outs[0].planta_nombre is None


def test_sic_con_varias_plantas_las_une(db):
    p1 = _planta(db, "Planta A")
    p2 = _planta(db, "Planta B")
    for pid in (p1.id, p2.id):
        _sol(db, proyecto_id=pid, codigo_sic_contrato="55555",
             tipo_solicitud=TipoSolicitudAsicEnum.registro,
             estado_solicitud=EstadoSolicitudAsicEnum.publicado)
    _sol(db, proyecto_id=None, codigo_sic_contrato="55555",
         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado)
    db.commit()
    outs = asic_api.list_solicitudes(codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None, db=db, _=None)
    term = next(o for o in outs if o.tipo_solicitud == TipoSolicitudAsicEnum.terminacion)
    assert term.planta_nombre in ("Planta A · Planta B", "Planta B · Planta A")


# ── El fecha_fin del contrato PPA macro es manual, nunca lo mueve ASIC ─────────
def _ppa(db, numero, fecha_fin):
    c = PPAContrato(id=next(_ids), numero_codigo_contrato=numero, nombre_interno=numero,
                    fecha_fin=fecha_fin)
    db.add(c)
    db.flush()
    return c


def test_terminar_una_planta_no_termina_el_contrato_multiplanta(db):
    """Terpel 1: PPA con 12 plantas hasta 2039. Terminar UNA planta (un SIC) NO debe
    mover el fin contractual del PPA."""
    ppa = _ppa(db, "UNERGY 001-2023", date(2039, 12, 31))
    # dos plantas abiertas (fecha_fin NULL) del mismo contrato interno, distinto SIC
    _sol(db, codigo_sic_contrato="111", contrato_interno="UNERGY 001-2023",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado, fecha_fin=None)
    _sol(db, codigo_sic_contrato="222", contrato_interno="UNERGY 001-2023",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado, fecha_fin=None)
    # terminación de la planta del SIC 111
    term = AsicSolicitud(id=next(_ids), codigo_sic_contrato="111",
                         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         fecha_fin=date(2024, 8, 30))
    db.add(term)
    db.commit()

    asic_api._auto_terminate(db, term)
    db.commit()
    db.refresh(ppa)

    assert ppa.fecha_fin == date(2039, 12, 31), (
        f"el contrato multi-planta no debe terminarse por una sola planta, "
        f"quedó en {ppa.fecha_fin}"
    )


def test_terminar_la_ultima_planta_tampoco_mueve_el_fecha_fin_del_ppa(db):
    """El fecha_fin del PPA es manual (fuente de verdad del contrato firmado):
    ni siquiera terminar TODAS las plantas de un contrato lo cambia automáticamente.
    Antes esto colapsaba el contrato a la fecha de la última planta en salir, lo que
    resultó frágil (ver test_asic_fecha_fin_random_repro.py)."""
    ppa = _ppa(db, "UNERGY 999-2023", date(2039, 12, 31))
    # una planta ya terminada antes, otra que terminamos ahora
    _sol(db, codigo_sic_contrato="333", contrato_interno="UNERGY 999-2023",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado, fecha_fin=date(2024, 5, 31))
    _sol(db, codigo_sic_contrato="444", contrato_interno="UNERGY 999-2023",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado, fecha_fin=None)
    term = AsicSolicitud(id=next(_ids), codigo_sic_contrato="444",
                         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         fecha_fin=date(2024, 8, 30))
    db.add(term)
    db.commit()

    asic_api._auto_terminate(db, term)
    db.commit()
    db.refresh(ppa)

    assert ppa.fecha_fin == date(2039, 12, 31), (
        f"el fecha_fin del PPA es manual, no debía moverse; quedó en {ppa.fecha_fin}"
    )


def test_terminar_planta_si_estampa_fecha_fin_en_registros_hermanos_del_mismo_sic(db):
    """El nivel planta se conserva: al terminar un SIC, sus propios registros/
    modificaciones (mismo SIC) sí reciben la fecha de terminación."""
    _sol(db, codigo_sic_contrato="555", contrato_interno="UNERGY 111-2023",
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         estado_solicitud=EstadoSolicitudAsicEnum.publicado, fecha_fin=None)
    term = AsicSolicitud(id=next(_ids), codigo_sic_contrato="555",
                         tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
                         estado_solicitud=EstadoSolicitudAsicEnum.publicado,
                         fecha_fin=date(2024, 8, 30))
    db.add(term)
    db.commit()

    asic_api._auto_terminate(db, term)
    db.commit()

    hermano = db.query(AsicSolicitud).filter(
        AsicSolicitud.codigo_sic_contrato == "555",
        AsicSolicitud.tipo_solicitud == TipoSolicitudAsicEnum.registro,
    ).first()
    assert hermano.fecha_fin == date(2024, 8, 30)
