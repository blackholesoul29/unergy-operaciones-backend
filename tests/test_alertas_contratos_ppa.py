"""/alertas/contratos-ppa: duplicados con vigencia EFECTIVA, no filas crudas.

El cálculo anterior (DISTINCT ON por fecha_solicitud) contaba filas ya
relevadas: una planta reubicada de contrato aparecía "activa en 2+ contratos a
la vez" (falso positivo — caso real: MGS 0012 La Reserva, SIC 89116). Ahora la
vigencia se resuelve con gescon_vigencia (mismo núcleo que Cumplimiento).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date, timedelta

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.cumplimiento import CumplimientoMensual
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1 import alertas as alertas_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__,
                CumplimientoMensual.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))

HOY = date.today()
FUTURO = HOY + timedelta(days=365 * 5)


def _planta(db, nombre):
    p = Proyecto(id=next(_ids), nombre_comercial=nombre,
                 tipo_proyecto="minigranja", estado="en_operacion")
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("reemplaza_anterior", True)
    # server_default="false" en SQLite queda como string 'false' (truthy):
    # hay que setearlo explícito en tests (en Postgres castea bien).
    kw.setdefault("es_duplicado", False)
    kw.setdefault("tipo_solicitud", TipoSolicitudAsicEnum.registro)
    db.add(AsicSolicitud(id=next(_ids), **kw))


def _duplicados(db):
    return alertas_api.alertas_contratos_ppa(db=db, _=None)["duplicados"]


def test_planta_reubicada_no_es_duplicado(db):
    """Caso La Reserva: relevada en su SIC viejo por otra planta → aunque su
    fila vieja conserve fecha_fin cruda futura, NO está en 2 contratos."""
    reserva = _planta(db, "MGS 0012 La Reserva")
    otra = _planta(db, "Planta Relevo")
    _sol(db, proyecto_id=reserva.id, codigo_sic_contrato="87137",
         contrato_interno="UNERGY 009-2025",
         fecha_inicio=date(2025, 4, 3), fecha_fin=FUTURO)
    _sol(db, proyecto_id=otra.id, codigo_sic_contrato="87137",
         contrato_interno="UNERGY 009-2025",
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_inicio=date(2026, 2, 7), fecha_fin=FUTURO)
    _sol(db, proyecto_id=reserva.id, codigo_sic_contrato="89116",
         contrato_interno="UNERGY 002-2024",
         fecha_inicio=date(2026, 2, 7), fecha_fin=FUTURO)
    db.commit()

    dups = _duplicados(db)
    assert [d for d in dups if d["proyecto_id"] == reserva.id] == [], (
        "la planta fue reubicada, no duplicada: su fila vieja ya no es la "
        "versión vigente del SIC 87137"
    )


def test_duplicado_real_sigue_alertando(db):
    """Control positivo: misma planta vigente en dos SICs sin relevo → alerta."""
    p = _planta(db, "Planta Doble")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="700",
         fecha_inicio=date(2025, 1, 1), fecha_fin=FUTURO)
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="701",
         fecha_inicio=date(2026, 1, 1), fecha_fin=FUTURO)
    db.commit()

    dups = _duplicados(db)
    mios = [d for d in dups if d["proyecto_id"] == p.id]
    assert len(mios) == 1
    assert {s["codigo_sic_contrato"] for s in mios[0]["sics"]} == {"700", "701"}


def test_bolsa_marcada_resuelve_el_duplicado(db):
    """es_duplicado=True (compra en bolsa) ya declaró el cruce → sin alerta."""
    p = _planta(db, "Planta Bolsa")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="800",
         fecha_inicio=date(2025, 1, 1), fecha_fin=FUTURO)
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="801", es_duplicado=True,
         fecha_inicio=date(2026, 1, 1), fecha_fin=FUTURO)
    db.commit()

    assert [d for d in _duplicados(db) if d["proyecto_id"] == p.id] == []


def test_modificacion_radicada_pero_sin_efecto_no_desplaza(db):
    """El bug de ordenar por fecha_solicitud: una modificación radicada ayer
    pero vigente el año entrante NO debe desplazar a la versión vigente hoy."""
    p = _planta(db, "Planta Estable")
    q = _planta(db, "Planta Futura")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="900",
         fecha_solicitud=date(2024, 1, 1),
         fecha_inicio=date(2024, 2, 1), fecha_fin=FUTURO)
    _sol(db, proyecto_id=q.id, codigo_sic_contrato="900",
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_solicitud=HOY,
         fecha_inicio=HOY + timedelta(days=200), fecha_fin=FUTURO)
    # Y P también está (legítimamente, sin relevo) en otro SIC → duplicado real
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="901",
         fecha_inicio=date(2025, 1, 1), fecha_fin=FUTURO)
    db.commit()

    dups = _duplicados(db)
    mios = [d for d in dups if d["proyecto_id"] == p.id]
    assert len(mios) == 1, (
        "P sigue vigente en 900 hoy (la modificación futura aún no releva) "
        "y en 901 → duplicado real con la versión vigente correcta"
    )
    assert {s["codigo_sic_contrato"] for s in mios[0]["sics"]} == {"900", "901"}
