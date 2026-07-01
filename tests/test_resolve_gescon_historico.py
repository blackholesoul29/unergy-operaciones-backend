"""_resolve_gescon debe reconstruir la vigencia HISTÓRICA por mes, no quedarse
con la versión más reciente global.

Bug real (Terpel 1, 2026): Vallenata tenía un registro al 100% vigente desde
2024-07-04, y una modificación al 50% vigente desde 2026-02-12 (radicada
2026-01-30, antes de fin de mes). Como el código viejo ordenaba/filtraba por
fecha_solicitud, la modificación desplazaba al registro viejo también en el
cálculo de enero-2026 (mes previo a que tomara efecto) y luego el filtro final
de fechas la descartaba a ella también → enero quedaba sin ninguna versión
(la planta desaparecía del contrato en vez de mostrar el 100%).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date, datetime, timezone

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1.cumplimiento import _resolve_gescon


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
    db.add(AsicSolicitud(id=next(_ids), **kw))


CONTRATO = "UNERGY 001-2023"


def _cargar_caso_vallenata(db):
    """Reproduce el registro + modificación reales de Vallenata en Terpel 1."""
    p = _planta(db, "MGS 0007 La Paz Vallenata")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="83155", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         fecha_solicitud=date(2024, 6, 22), fecha_inicio=date(2024, 7, 4),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0,
         created_at=datetime(2024, 6, 22, tzinfo=timezone.utc))
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="83155", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_solicitud=date(2026, 1, 30), fecha_inicio=date(2026, 2, 12),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=0.5,
         created_at=datetime(2026, 5, 2, tzinfo=timezone.utc))
    db.commit()
    return p


def test_mes_anterior_a_la_modificacion_usa_la_version_vieja(db):
    """Enero-2026: la modificación (vigente desde feb-12) todavía no tomaba
    efecto → debe verse el registro viejo al 100%, no desaparecer."""
    _cargar_caso_vallenata(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 1)
    assert len(asics) == 1, "la planta no debería desaparecer en enero"
    assert float(asics[0].porcentaje_despacho) == 1.0


def test_mes_de_la_modificacion_usa_la_version_nueva(db):
    """Febrero-2026: la modificación ya tomó efecto (12-feb) → 50%, no 100%."""
    _cargar_caso_vallenata(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    assert len(asics) == 1
    assert float(asics[0].porcentaje_despacho) == 0.5
    assert asics[0].fecha_inicio == date(2026, 2, 12)


def test_meses_posteriores_siguen_en_la_version_nueva(db):
    _cargar_caso_vallenata(db)
    for month in (3, 6, 12):
        asics = _resolve_gescon(db, CONTRATO, 2026, month)
        assert len(asics) == 1
        assert float(asics[0].porcentaje_despacho) == 0.5


def test_mes_muy_anterior_al_registro_no_trae_nada(db):
    """2024-01, antes de que existiera cualquier registro (fecha_inicio 2024-07-04)."""
    _cargar_caso_vallenata(db)
    asics = _resolve_gescon(db, CONTRATO, 2024, 1)
    assert asics == []


def test_terminacion_sigue_excluyendo_meses_posteriores():
    """Una terminación (fecha_fin estampada en el registro/modificación del
    mismo SIC, como hace _auto_terminate) debe seguir excluyendo el mes."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
    )
    db = sessionmaker(bind=engine)()
    try:
        p = _planta(db, "Planta Terminada")
        _sol(db, proyecto_id=p.id, codigo_sic_contrato="111", contrato_interno=CONTRATO,
             tipo_solicitud=TipoSolicitudAsicEnum.registro,
             fecha_solicitud=date(2024, 1, 1), fecha_inicio=date(2024, 1, 1),
             fecha_fin=date(2024, 8, 30), porcentaje_despacho=1.0)
        db.commit()

        assert len(_resolve_gescon(db, CONTRATO, 2024, 6)) == 1
        assert _resolve_gescon(db, CONTRATO, 2024, 9) == []
    finally:
        db.close()


def test_reemplaza_anterior_sigue_funcionando_por_mes():
    """Una planta nueva con reemplaza_anterior=True debe seguir desplazando a
    la anterior en el SIC — pero solo a partir de su propia fecha_inicio."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
    )
    db = sessionmaker(bind=engine)()
    try:
        vieja = _planta(db, "Planta Vieja")
        nueva = _planta(db, "Planta Nueva")
        _sol(db, proyecto_id=vieja.id, codigo_sic_contrato="222", contrato_interno=CONTRATO,
             tipo_solicitud=TipoSolicitudAsicEnum.registro,
             fecha_solicitud=date(2024, 1, 1), fecha_inicio=date(2024, 1, 1),
             fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
        _sol(db, proyecto_id=nueva.id, codigo_sic_contrato="222", contrato_interno=CONTRATO,
             tipo_solicitud=TipoSolicitudAsicEnum.registro, reemplaza_anterior=True,
             fecha_solicitud=date(2025, 5, 1), fecha_inicio=date(2025, 6, 1),
             fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
        db.commit()

        antes = _resolve_gescon(db, CONTRATO, 2025, 3)
        assert len(antes) == 1 and antes[0].proyecto_id == vieja.id

        despues = _resolve_gescon(db, CONTRATO, 2025, 8)
        assert len(despues) == 1 and despues[0].proyecto_id == nueva.id
    finally:
        db.close()
