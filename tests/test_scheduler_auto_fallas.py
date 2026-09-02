"""_auto_create_fallas / _auto_close_fallas (app.services.mgs.scheduler) --
integración contra una BD real (SQLite en memoria), no solo la función pura.

Cubre específicamente la regresión del bug de emparejamiento por texto
(auditoría 2026-09-01, commit d28eb27): ambas funciones identificaban la
falla correspondiente a una alarma parseando el prefijo "[TIPO] ..." de
`descripcion` con ILIKE -- si alguien editaba esa descripción a mano
(soportado por PATCH /fallas/{id}), el match se rompía en silencio. El fix
usa `alarmas_monitoreo.alarm_type` (vía `Falla.alarma_monitoreo_id`) en vez
de texto libre; estos tests verifican que sobrevive a una descripción
editada, que antes rompía el flujo."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
import app.models  # noqa: F401
from app.models.fallas import (
    Falla, FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria,
    FallaCatResolucion, FallaSeguimiento, FallaIntervalo, FallaInversor,
)
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.services.mgs.alarm_engine import Alarm, AlarmType, Severity
from app.services.mgs.scheduler import _auto_close_fallas, _auto_create_fallas


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 9, 1)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, Usuario.__table__,
        FallaCatCategoria.__table__, FallaCatTipo.__table__, FallaCatEstado.__table__,
        FallaCatPrioridad.__table__, FallaCatResolucion.__table__,
        Falla.__table__, FallaSeguimiento.__table__, FallaIntervalo.__table__,
        FallaInversor.__table__,
    ])
    s = sessionmaker(bind=engine)()
    # alarmas_monitoreo no tiene modelo ORM (ver auditoría 2026-09-01) --
    # se crea a mano, igual que en producción (alembic 135).
    s.execute(text("""
        CREATE TABLE alarmas_monitoreo (
            id INTEGER PRIMARY KEY,
            proyecto_nombre TEXT,
            severity TEXT,
            alarm_type TEXT,
            details TEXT,
            created_at TEXT,
            resolved_at TEXT
        )
    """))
    s.commit()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def base(db):
    """Catálogo mínimo + un proyecto + un usuario admin, requeridos por
    _auto_create_fallas/_auto_close_fallas."""
    estado_abierta = FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta",
                                     orden=1, es_estado_final=False)
    estado_cerrada = FallaCatEstado(id=2, codigo="cerrada", etiqueta="Cerrada",
                                     orden=2, es_estado_final=True)
    db.add_all([estado_abierta, estado_cerrada])

    categoria = FallaCatCategoria(id=1, codigo="red", etiqueta="Red", activa=True)
    db.add(categoria)
    tipo = FallaCatTipo(id=1, categoria_id=1, codigo="9.1",
                        etiqueta="Sin Suministro Electrico", activa=True)
    db.add(tipo)

    # Códigos reales de fallas_cat_prioridades (ver app/seeds/seed_data.py) --
    # antes este fixture sembraba "alta", que no existe en producción, y eso
    # tapó durante un tiempo el bug real de _auto_create_fallas() usando ese
    # mismo código inexistente (auditoría 2026-09-02).
    db.add(FallaCatPrioridad(id=1, codigo="critica", etiqueta="Critica", nivel=1))
    db.add(FallaCatPrioridad(id=2, codigo="grave", etiqueta="Grave", nivel=2))

    db.add(Usuario(id=1, nombre="Admin", email="admin@unergy.io",
                   password_hash="x", rol="admin", activo=True))

    planta = Proyecto(id=10, nombre_comercial="Planta Test", sub_project="PT",
                      estado="en_operacion")
    db.add(planta)
    db.commit()
    return {"planta": planta, "estado_abierta": estado_abierta, "estado_cerrada": estado_cerrada}


def _insertar_alarma_monitoreo(db, alarm_id, alarm_type):
    db.execute(text(
        "INSERT INTO alarmas_monitoreo (id, proyecto_nombre, severity, alarm_type, details, created_at) "
        "VALUES (:id, 'Planta Test', 'CRITICAL', :tipo, 'x', :ts)"
    ), {"id": alarm_id, "tipo": alarm_type.value, "ts": HOY.isoformat()})
    db.commit()


def _alarm(alarm_type, severity=Severity.CRITICAL, proyecto_id=10):
    return Alarm(
        severity=severity, alarm_type=alarm_type, proyecto_id=proyecto_id,
        proyecto_nombre="Planta Test", category="ELECTRICAL_GENERATION",
        details="detalle", timestamp=dt.datetime(2026, 9, 1, 12, 0, 0),
    )


def test_auto_create_no_duplica_si_descripcion_fue_editada(db, base):
    """Regresión: antes del fix, _auto_create_fallas buscaba '[PLANTA_CAIDA]'
    en descripcion -- si un operador la reescribía, ya no encontraba la
    falla abierta y creaba un duplicado en la siguiente alarma."""
    _insertar_alarma_monitoreo(db, alarm_id=1, alarm_type=AlarmType.PLANTA_CAIDA)
    db.add(Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="Se cayó el breaker principal, cuadrilla en sitio",  # editada a mano
        fecha_identificacion=HOY, alarma_monitoreo_id=1,
    ))
    db.commit()

    _auto_create_fallas(db, [(_alarm(AlarmType.PLANTA_CAIDA), 2)])

    fallas = db.query(Falla).filter(Falla.proyecto_id == 10, Falla.deleted_at.is_(None)).all()
    assert len(fallas) == 1, "no debía crear una falla duplicada"


def test_auto_create_si_crea_para_alarma_de_otro_tipo(db, base):
    """Control: una falla abierta de PLANTA_CAIDA no bloquea la creación de
    una falla nueva para SIN_GENERACION del mismo proyecto (son alarm_type
    distintos)."""
    tipo_sin_gen = FallaCatTipo(id=2, categoria_id=1, codigo="4.6",
                               etiqueta="Inversor degradado", activa=True)
    db.add(tipo_sin_gen)
    db.commit()

    _insertar_alarma_monitoreo(db, alarm_id=1, alarm_type=AlarmType.PLANTA_CAIDA)
    db.add(Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="cualquier cosa", fecha_identificacion=HOY,
        alarma_monitoreo_id=1,
    ))
    db.commit()

    _auto_create_fallas(db, [(_alarm(AlarmType.SIN_GENERACION, severity=Severity.WARNING), 2)])

    fallas = db.query(Falla).filter(Falla.proyecto_id == 10, Falla.deleted_at.is_(None)).all()
    assert len(fallas) == 2


def test_auto_create_alarma_no_critica_usa_prioridad_grave_real(db, base):
    """Regresión: prioridad_code usaba "alta" para severidad no-CRITICAL, un
    código que no existe en fallas_cat_prioridades (real: critica/grave/media/
    leve) -- la búsqueda nunca encontraba fila, y `continue` se comía la
    creación en silencio para toda alarma no-crítica. Confirma que ahora sí
    se crea, con la prioridad real "grave" y su SLA correspondiente
    (auditoría 2026-09-02)."""
    _auto_create_fallas(db, [(_alarm(AlarmType.PLANTA_CAIDA, severity=Severity.WARNING), 1)])

    falla = db.query(Falla).filter(Falla.proyecto_id == 10).one()
    assert falla.prioridad_id == 2  # "grave", ver fixture `base`
    assert falla.sla_limite_horas == 24


def test_auto_create_codigo_interno_usa_el_id_real_asignado(db, base):
    """Regresión: antes, codigo_interno se armaba con MAX(id)+1 calculado
    ANTES del insert -- si dos fallas se creaban casi al mismo tiempo, ambas
    podían calcular el mismo número y chocar contra el unique=True de
    codigo_interno. El fix inserta con un placeholder, deja que la BD asigne
    el id real (RETURNING), y recién ahí arma el código -- igual que
    create_falla() en api/v1/fallas.py (auditoría 2026-09-02)."""
    _auto_create_fallas(db, [(_alarm(AlarmType.PLANTA_CAIDA), 1)])

    falla = db.query(Falla).filter(Falla.proyecto_id == 10).one()
    assert falla.codigo_interno == f"FAL-{HOY.year}-{falla.id:05d}"
    assert not falla.codigo_interno.startswith("TMP-")


def test_auto_close_cierra_pese_a_descripcion_editada(db, base):
    """Regresión: antes del fix, _auto_close_fallas buscaba '[PLANTA_CAIDA]'
    en descripcion para saber qué falla cerrar tras una RECUPERACION -- si
    un operador la reescribía, la falla quedaba abierta para siempre pese a
    que el sistema sí detectó la recuperación."""
    _insertar_alarma_monitoreo(db, alarm_id=1, alarm_type=AlarmType.PLANTA_CAIDA)
    db.add(Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=10,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="Se cayó el breaker principal, cuadrilla en sitio",  # editada a mano
        fecha_identificacion=HOY, alarma_monitoreo_id=1,
    ))
    db.commit()

    _auto_close_fallas(db, [(_alarm(AlarmType.RECUPERACION, severity=Severity.INFO), 2)])

    falla = db.get(Falla, 1)
    assert falla.estado_id == base["estado_cerrada"].id
    assert falla.fecha_resolucion is not None


def test_auto_close_no_toca_fallas_de_otro_proyecto(db, base):
    otro = Proyecto(id=11, nombre_comercial="Otra Planta", sub_project="OP",
                    estado="en_operacion")
    db.add(otro)
    _insertar_alarma_monitoreo(db, alarm_id=1, alarm_type=AlarmType.PLANTA_CAIDA)
    db.add(Falla(
        id=1, codigo_interno="FAL-2026-00001", proyecto_id=11,
        estado_id=1, prioridad_id=1, registrado_por_id=1,
        descripcion="falla de la otra planta", fecha_identificacion=HOY,
        alarma_monitoreo_id=1,
    ))
    db.commit()

    _auto_close_fallas(db, [(_alarm(AlarmType.RECUPERACION, severity=Severity.INFO, proyecto_id=10), 2)])

    falla = db.get(Falla, 1)
    assert falla.estado_id == base["estado_abierta"].id, "no debía cerrar la falla de otro proyecto"
