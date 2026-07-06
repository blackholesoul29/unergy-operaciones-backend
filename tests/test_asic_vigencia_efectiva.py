"""GET /asic expone fecha_fin_efectiva / es_version_vigente por fila.

Caso motivador: falso positivo de solapamiento en GESCON (SIC 89116, MGS 0012
La Reserva). La fila vieja de la planta en su SIC anterior conserva fecha_fin
cruda 2030/2039 aunque una modificación con otra planta la relevó; la validación
del frontend comparaba contra esa fecha cruda. El endpoint ahora publica la
ventana EFECTIVA para que cualquier consumidor compare contra la realidad.

Clave: la resolución corre sobre el universo completo de publicadas, no sobre
el subconjunto filtrado del request (el relevo puede venir de una planta que el
filtro excluye).
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


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
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
    s = AsicSolicitud(id=next(_ids), **kw)
    db.add(s)
    return s


def _cargar_caso_la_reserva(db):
    reserva = _planta(db, "MGS 0012 La Reserva")
    otra = _planta(db, "Planta Relevo")
    vieja = _sol(db, proyecto_id=reserva.id, codigo_sic_contrato="87137",
                 contrato_interno="UNERGY 009-2025",
                 tipo_solicitud=TipoSolicitudAsicEnum.registro,
                 fecha_inicio=date(2025, 4, 3), fecha_fin=date(2030, 3, 31))
    relevo = _sol(db, proyecto_id=otra.id, codigo_sic_contrato="87137",
                  contrato_interno="UNERGY 009-2025",
                  tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
                  fecha_inicio=date(2026, 2, 7), fecha_fin=date(2030, 3, 31))
    nueva = _sol(db, proyecto_id=reserva.id, codigo_sic_contrato="89116",
                 contrato_interno="UNERGY 002-2024",
                 tipo_solicitud=TipoSolicitudAsicEnum.registro,
                 fecha_inicio=date(2026, 2, 7), fecha_fin=date(2039, 12, 31))
    db.commit()
    return reserva, vieja, relevo, nueva


def test_list_expone_ventana_efectiva_recortada(db):
    _, vieja, _, nueva = _cargar_caso_la_reserva(db)
    outs = asic_api.list_solicitudes(db=db, _=None,
                                     codigo_sic_contrato=None,
                                     contrato_interno=None, proyecto_id=None)
    por_id = {o.id: o for o in outs}
    assert por_id[vieja.id].fecha_fin_efectiva == date(2026, 2, 6)
    assert por_id[vieja.id].es_version_vigente is False
    assert por_id[vieja.id].fecha_fin == date(2030, 3, 31), "la cruda no se toca"
    assert por_id[nueva.id].fecha_fin_efectiva == date(2039, 12, 31)
    assert por_id[nueva.id].es_version_vigente is True


def test_filtro_por_proyecto_no_pierde_el_recorte(db):
    """El relevo viene de OTRA planta: aunque el filtro excluya esa fila, la
    resolución debe correr sobre el universo completo y recortar igual."""
    reserva, vieja, _, _ = _cargar_caso_la_reserva(db)
    outs = asic_api.list_solicitudes(db=db, _=None,
                                     codigo_sic_contrato=None,
                                     contrato_interno=None,
                                     proyecto_id=reserva.id)
    por_id = {o.id: o for o in outs}
    assert set(por_id) == {vieja.id, [o.id for o in outs if o.codigo_sic_contrato == "89116"][0]}
    assert por_id[vieja.id].fecha_fin_efectiva == date(2026, 2, 6)


def test_fila_no_publicada_pasa_cruda_y_no_vigente(db):
    p = _planta(db, "Planta En Proceso")
    s = _sol(db, proyecto_id=p.id, codigo_sic_contrato="500",
             estado_solicitud=EstadoSolicitudAsicEnum.en_proceso,
             tipo_solicitud=TipoSolicitudAsicEnum.registro,
             fecha_inicio=date(2026, 1, 1), fecha_fin=date(2039, 12, 31))
    db.commit()
    outs = asic_api.list_solicitudes(db=db, _=None,
                                     codigo_sic_contrato=None,
                                     contrato_interno=None, proyecto_id=None)
    o = next(x for x in outs if x.id == s.id)
    assert o.fecha_fin_efectiva == date(2039, 12, 31)
    assert o.es_version_vigente is False
