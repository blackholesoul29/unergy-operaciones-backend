"""Cobertura ASIC de los PPA activos: /asic/ppa-status y /alertas/riesgo-asic.

El punto fino: "publicado" NO es lo mismo que "cubre hoy". Una fila publicada
puede haber sido relevada por una modificación posterior o terminada, y conserva
su `fecha_fin` CRUDA (futura) — compararla daría un falso "cubierto". La
cobertura se decide sobre la vigencia EFECTIVA (gescon_vigencia), igual que en
Cumplimiento y /alertas/contratos-ppa.
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
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1 import alertas as alertas_api
from app.schemas.asic_status import AsicStatus
from app.services.asic_monitor import (
    RegistroAsic,
    clasificar_cobertura,
    get_ppa_asic_status,
    ppa_activo,
)


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

HOY = date.today()
FUTURO = HOY + timedelta(days=365 * 5)
PASADO = HOY - timedelta(days=365)


def _hace(dias: int) -> date:
    return HOY - timedelta(days=dias)


def _ppa(db, nombre, **kw):
    kw.setdefault("fecha_inicio", _hace(400))
    kw.setdefault("fecha_fin", FUTURO)
    c = PPAContrato(id=next(_ids), nombre_interno=nombre, **kw)
    db.add(c)
    db.flush()
    return c


def _planta(db, nombre):
    p = Proyecto(id=next(_ids), nombre_comercial=nombre,
                 tipo_proyecto="minigranja", estado="en_operacion")
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("tipo_solicitud", TipoSolicitudAsicEnum.registro)
    kw.setdefault("reemplaza_anterior", True)
    # server_default="false" en SQLite queda como string 'false' (truthy):
    # hay que setearlo explícito en tests (en Postgres castea bien).
    kw.setdefault("es_duplicado", False)
    kw.setdefault("uso_del_recurso", False)
    kw.setdefault("fecha_inicio", _hace(300))
    kw.setdefault("fecha_solicitud", _hace(300))
    s = AsicSolicitud(id=next(_ids), **kw)
    db.add(s)
    db.flush()
    return s


def _por_ppa(filas):
    return {f.ppa_id: f for f in filas}


# ── Función pura: la regla de clasificación ─────────────────────────────────

def _reg(**kw):
    kw.setdefault("id", next(_ids))
    kw.setdefault("estado", "publicado")
    kw.setdefault("tipo", "registro")
    kw.setdefault("fecha_inicio", _hace(300))
    kw.setdefault("fecha_fin_efectiva", FUTURO)
    kw.setdefault("vigente", True)
    kw.setdefault("fecha_radicacion", _hace(300))
    return RegistroAsic(**kw)


def test_sin_registros_es_ninguna_y_critico():
    c = clasificar_cobertura([], HOY, umbral_dias=15)
    assert c.status == AsicStatus.NINGUNA
    assert c.es_critico is True
    assert c.asic_solicitud_id is None


def test_registro_publicado_vigente_cubre_hoy():
    c = clasificar_cobertura([_reg(id=7)], HOY, umbral_dias=15)
    assert (c.status, c.asic_solicitud_id, c.es_critico) == (AsicStatus.PUBLICADA, 7, False)


def test_registro_publicado_pero_relevado_no_cubre():
    """El caso que motiva usar vigencia efectiva: la fila sigue 'publicado' y su
    fecha_fin cruda es futura, pero una modificación posterior la relevó."""
    c = clasificar_cobertura([_reg(vigente=False, fecha_fin_efectiva=_hace(30))], HOY, umbral_dias=15)
    assert c.status == AsicStatus.PENDIENTE


def test_registro_publicado_vencido_no_cubre():
    c = clasificar_cobertura([_reg(fecha_fin_efectiva=_hace(1))], HOY, umbral_dias=15)
    assert c.status == AsicStatus.PENDIENTE


def test_ventana_abierta_sigue_cubriendo():
    """fecha_fin_efectiva None = ventana abierta, no 'sin fin conocido' → cubre."""
    assert clasificar_cobertura([_reg(fecha_fin_efectiva=None)], HOY, 15).status == AsicStatus.PUBLICADA


def test_registro_con_inicio_futuro_no_cubre_hoy():
    futuro = _reg(fecha_inicio=HOY + timedelta(days=10), fecha_radicacion=_hace(2))
    assert clasificar_cobertura([futuro], HOY, 15).status == AsicStatus.PENDIENTE


def test_terminacion_publicada_no_es_cobertura():
    assert clasificar_cobertura([_reg(tipo="terminacion")], HOY, 15).status == AsicStatus.PENDIENTE


def test_en_proceso_es_pendiente():
    c = clasificar_cobertura([_reg(estado="en_proceso", vigente=False)], HOY, 15)
    assert c.status == AsicStatus.PENDIENTE


def test_umbral_configurable_y_exacto_no_alerta():
    """Igual que calcular_alerta del CRM: el día exacto del umbral NO alerta."""
    en_proceso = dict(estado="en_proceso", vigente=False)
    c15 = clasificar_cobertura([_reg(**en_proceso, fecha_radicacion=_hace(15))], HOY, umbral_dias=15)
    assert (c15.dias_pendiente, c15.es_critico) == (15, False)

    c16 = clasificar_cobertura([_reg(**en_proceso, fecha_radicacion=_hace(16))], HOY, umbral_dias=15)
    assert (c16.dias_pendiente, c16.es_critico) == (16, True)

    # Con umbral 30, esos mismos 16 días ya no son críticos.
    c30 = clasificar_cobertura([_reg(**en_proceso, fecha_radicacion=_hace(16))], HOY, umbral_dias=30)
    assert c30.es_critico is False


def test_pendiente_toma_el_registro_mas_reciente():
    viejo = _reg(id=100, estado="en_proceso", vigente=False, fecha_radicacion=_hace(200))
    nuevo = _reg(id=101, estado="en_proceso", vigente=False, fecha_radicacion=_hace(3))
    c = clasificar_cobertura([viejo, nuevo], HOY, umbral_dias=15)
    # Manda el trámite en curso más nuevo: 3 días, aún no crítico.
    assert (c.asic_solicitud_id, c.dias_pendiente, c.es_critico) == (101, 3, False)


def test_cobertura_vigente_gana_sobre_filas_muertas():
    muerta = _reg(id=1, vigente=False, fecha_fin_efectiva=_hace(30))
    viva = _reg(id=2)
    assert clasificar_cobertura([muerta, viva], HOY, 15).status == AsicStatus.PUBLICADA


# ── ppa_activo: no hay columna `estado`, la ventana manda ────────────────────

def test_ppa_activo_segun_ventana():
    assert ppa_activo(PPAContrato(fecha_inicio=_hace(10), fecha_fin=FUTURO), HOY) is True
    assert ppa_activo(PPAContrato(fecha_inicio=None, fecha_fin=None), HOY) is True
    assert ppa_activo(PPAContrato(fecha_inicio=_hace(400), fecha_fin=_hace(1)), HOY) is False
    assert ppa_activo(PPAContrato(fecha_inicio=HOY + timedelta(days=1), fecha_fin=FUTURO), HOY) is False


# ── Endpoint / servicio contra la DB ────────────────────────────────────────

def test_clasifica_los_tres_casos(db):
    """Fixture del plan de pruebas: uno publicado, uno pendiente, uno sin ASIC."""
    p = _planta(db, "Planta 1")
    con_asic = _ppa(db, "PPA Publicado")
    pendiente = _ppa(db, "PPA Pendiente")
    sin_asic = _ppa(db, "PPA Sin ASIC")

    _sol(db, contrato_ppa_id=con_asic.id, proyecto_id=p.id,
         codigo_sic_contrato="900", fecha_fin=FUTURO)
    _sol(db, contrato_ppa_id=pendiente.id, proyecto_id=p.id,
         codigo_sic_contrato="901", fecha_fin=FUTURO,
         estado_solicitud=EstadoSolicitudAsicEnum.en_proceso,
         fecha_solicitud=_hace(3))
    db.commit()

    filas = _por_ppa(get_ppa_asic_status(db, hoy=HOY, umbral_dias=15))

    assert filas[con_asic.id].asic_status == AsicStatus.PUBLICADA
    assert filas[con_asic.id].es_critico is False
    assert filas[con_asic.id].codigo_sic_contrato == "900"

    assert filas[pendiente.id].asic_status == AsicStatus.PENDIENTE
    assert filas[pendiente.id].dias_pendiente == 3
    assert filas[pendiente.id].es_critico is False  # 3 días < umbral 15

    assert filas[sin_asic.id].asic_status == AsicStatus.NINGUNA
    assert filas[sin_asic.id].asic_solicitud_id is None
    assert filas[sin_asic.id].es_critico is True


def test_pendiente_viejo_es_critico(db):
    viejo = _ppa(db, "PPA Radicado Hace Meses")
    _sol(db, contrato_ppa_id=viejo.id, codigo_sic_contrato="910", fecha_fin=FUTURO,
         estado_solicitud=EstadoSolicitudAsicEnum.en_proceso, fecha_solicitud=_hace(60))
    db.commit()

    fila = _por_ppa(get_ppa_asic_status(db, hoy=HOY, umbral_dias=15))[viejo.id]
    assert (fila.asic_status, fila.dias_pendiente, fila.es_critico) == (AsicStatus.PENDIENTE, 60, True)


def test_is_critical_only_filtra(db):
    cubierto = _ppa(db, "PPA OK")
    sin_asic = _ppa(db, "PPA Sin ASIC")
    _sol(db, contrato_ppa_id=cubierto.id, codigo_sic_contrato="920", fecha_fin=FUTURO)
    db.commit()

    criticos = get_ppa_asic_status(db, is_critical_only=True, hoy=HOY, umbral_dias=15)
    assert [f.ppa_id for f in criticos] == [sin_asic.id]
    assert all(f.es_critico for f in criticos)


def test_status_filter(db):
    cubierto = _ppa(db, "PPA OK")
    _ppa(db, "PPA Sin ASIC")
    _sol(db, contrato_ppa_id=cubierto.id, codigo_sic_contrato="930", fecha_fin=FUTURO)
    db.commit()

    solo_pub = get_ppa_asic_status(db, status_filter=AsicStatus.PUBLICADA, hoy=HOY)
    assert [f.ppa_id for f in solo_pub] == [cubierto.id]


def test_ppa_vencido_no_se_reporta(db):
    """Un PPA que terminó en 2025 sin GESCON no es un riesgo: es historia."""
    _ppa(db, "PPA Vencido", fecha_inicio=_hace(800), fecha_fin=PASADO)
    activo = _ppa(db, "PPA Activo")
    db.commit()

    assert [f.ppa_id for f in get_ppa_asic_status(db, hoy=HOY)] == [activo.id]


def test_ligadura_por_contrato_interno_sin_fk(db):
    """Registros viejos sin contrato_ppa_id se casan por numero_codigo_contrato.
    Sin este fallback el contrato aparecería como NINGUNA → falso crítico."""
    c = _ppa(db, "PPA Legacy", numero_codigo_contrato="UNERGY 009-2025")
    _sol(db, contrato_interno="UNERGY 009-2025", codigo_sic_contrato="940", fecha_fin=FUTURO)
    db.commit()

    fila = _por_ppa(get_ppa_asic_status(db, hoy=HOY))[c.id]
    assert fila.asic_status == AsicStatus.PUBLICADA
    assert fila.es_critico is False


def test_registro_relevado_deja_al_ppa_sin_cobertura(db):
    """La planta del SIC fue reubicada a OTRO contrato: la fila vieja sigue
    'publicado' con fecha_fin cruda futura, pero ya no es la versión vigente.
    Su PPA queda descubierto — y es exactamente lo que hay que alertar."""
    reserva = _planta(db, "MGS 0012 La Reserva")
    otra = _planta(db, "Planta Relevo")
    viejo = _ppa(db, "PPA Viejo", numero_codigo_contrato="UNERGY 009-2025")
    nuevo = _ppa(db, "PPA Nuevo", numero_codigo_contrato="UNERGY 002-2024")

    # Ambos registros comparten SIC: el segundo releva al primero.
    _sol(db, contrato_ppa_id=viejo.id, proyecto_id=reserva.id, codigo_sic_contrato="87137",
         fecha_inicio=_hace(300), fecha_solicitud=_hace(300), fecha_fin=FUTURO)
    _sol(db, contrato_ppa_id=nuevo.id, proyecto_id=otra.id, codigo_sic_contrato="87137",
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_inicio=_hace(30), fecha_solicitud=_hace(30), fecha_fin=FUTURO)
    db.commit()

    filas = _por_ppa(get_ppa_asic_status(db, hoy=HOY, umbral_dias=15))
    assert filas[nuevo.id].asic_status == AsicStatus.PUBLICADA
    assert filas[viejo.id].asic_status == AsicStatus.PENDIENTE, (
        "la fila conserva fecha_fin cruda futura, pero fue relevada: no cubre hoy"
    )
    assert filas[viejo.id].es_critico is True  # radicado hace 300 días


def test_registro_terminado_deja_al_ppa_sin_cobertura(db):
    """GESCON terminado (fecha_fin estampada por _auto_terminate) pero contrato
    comercial aún abierto → riesgo real: se entrega energía sin registro vivo."""
    c = _ppa(db, "PPA Con GESCON Terminado")
    _sol(db, contrato_ppa_id=c.id, codigo_sic_contrato="950",
         fecha_inicio=_hace(300), fecha_solicitud=_hace(300), fecha_fin=_hace(10))
    db.commit()

    fila = _por_ppa(get_ppa_asic_status(db, hoy=HOY, umbral_dias=15))[c.id]
    assert (fila.asic_status, fila.es_critico) == (AsicStatus.PENDIENTE, True)


def test_ppa_borrado_no_se_reporta(db):
    from datetime import datetime, timezone
    _ppa(db, "PPA Borrado", deleted_at=datetime.now(timezone.utc))
    db.commit()

    assert get_ppa_asic_status(db, hoy=HOY) == []


def test_criticos_primero_en_el_orden(db):
    cubierto = _ppa(db, "PPA OK")
    sin_asic = _ppa(db, "PPA Sin ASIC")
    _sol(db, contrato_ppa_id=cubierto.id, codigo_sic_contrato="960", fecha_fin=FUTURO)
    db.commit()

    assert [f.ppa_id for f in get_ppa_asic_status(db, hoy=HOY)] == [sin_asic.id, cubierto.id]


# ── Alertas ─────────────────────────────────────────────────────────────────

def test_payload_de_alerta(db):
    sin_asic = _ppa(db, "PPA Sin ASIC")
    cubierto = _ppa(db, "PPA OK")
    _sol(db, contrato_ppa_id=cubierto.id, codigo_sic_contrato="970", fecha_fin=FUTURO)
    db.commit()

    alertas = alertas_api.generar_alertas_riesgo_asic(db, umbral_dias=15, hoy=HOY)

    assert len(alertas) == 1
    a = alertas[0]
    assert a["tipo"] == "RIESGO_ASIC"
    assert a["ppa_id"] == sin_asic.id
    assert a["mensaje"] == "PPA activo sin asignación ASIC publicada"
    assert a["severidad"] == "ALTA"


def test_alerta_de_pendiente_vencido_menciona_los_dias(db):
    c = _ppa(db, "PPA Pendiente Viejo")
    _sol(db, contrato_ppa_id=c.id, codigo_sic_contrato="980", fecha_fin=FUTURO,
         estado_solicitud=EstadoSolicitudAsicEnum.en_proceso, fecha_solicitud=_hace(40))
    db.commit()

    alertas = alertas_api.generar_alertas_riesgo_asic(db, umbral_dias=15, hoy=HOY)
    assert len(alertas) == 1
    assert alertas[0]["asic_status"] == "PENDIENTE"
    assert alertas[0]["dias_pendiente"] == 40
    assert "40 días" in alertas[0]["mensaje"]


def test_sin_criticos_no_hay_alertas(db):
    c = _ppa(db, "PPA OK")
    _sol(db, contrato_ppa_id=c.id, codigo_sic_contrato="990", fecha_fin=FUTURO)
    db.commit()

    assert alertas_api.generar_alertas_riesgo_asic(db, umbral_dias=15, hoy=HOY) == []
