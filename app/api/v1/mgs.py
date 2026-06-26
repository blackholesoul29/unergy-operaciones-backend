"""MGS Alarms — real-time solar plant monitoring endpoints.

Además de exponer las alarmas del MGS, este módulo aloja el detector de
*eventos críticos* (caída de producción / desconexión total) que genera fallas
con ``origen=MGS_CRITICA`` y notifica in-app a los usuarios de operaciones con un
enlace directo al detalle de la falla. Ver ``check_mgs_critical_events``.
"""
import calendar
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import bindparam, text

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.schemas.fallas import OrigenFalla, TipoAlertaMGS
from app.services.mgs import scheduler

logger = logging.getLogger("mgs.critical")

router = APIRouter(prefix="/mgs", tags=["MGS Monitoreo"])


# ── Detector de eventos críticos (lógica pura, sin DB) ────────────────────────
class MGSCriticalDetector:
    """Clasifica la generación de un proyecto y decide cuándo emitir una alerta.

    Mantiene estado por proyecto para:
      - exigir una duración sostenida en cero antes de declarar desconexión total
        (``disconnection_minutes``), evitando falsas alarmas por un único poll;
      - hacer *debounce*: una incidencia en curso se notifica una sola vez y solo
        vuelve a notificarse tras una recuperación.

    El estado es en memoria (suficiente para el ciclo del scheduler); ante un
    reinicio del proceso a lo sumo se re-emite una alerta por incidencia activa,
    y ``check_mgs_critical_events`` evita duplicar la falla consultando la BD.
    """

    def __init__(self, drop_threshold: float, disconnection_minutes: int):
        self.drop_threshold = drop_threshold
        self.disconnection_minutes = disconnection_minutes
        self._zero_since: dict[int, datetime] = {}
        self._active: dict[int, TipoAlertaMGS] = {}

    def _raw_event(
        self, proyecto_id: int, current_gen: Optional[float],
        expected_gen: Optional[float], now: datetime,
    ) -> Optional[TipoAlertaMGS]:
        """Evento candidato sin aplicar debounce (sí aplica duración sostenida)."""
        if expected_gen is None or expected_gen <= 0:
            self._zero_since.pop(proyecto_id, None)
            return None

        gen = current_gen if current_gen is not None else 0.0

        if gen <= 0:
            first = self._zero_since.get(proyecto_id)
            if first is None:
                self._zero_since[proyecto_id] = now
                return None
            if (now - first) >= timedelta(minutes=self.disconnection_minutes):
                return TipoAlertaMGS.DESCONEXION_TOTAL
            return None

        # gen > 0 → reinicia la ventana de desconexión
        self._zero_since.pop(proyecto_id, None)
        if gen < expected_gen * (1 - self.drop_threshold):
            return TipoAlertaMGS.CAIDA_PRODUCCION
        return None

    def evaluate(
        self, proyecto_id: int, current_gen: Optional[float],
        expected_gen: Optional[float], now: datetime,
    ) -> Optional[TipoAlertaMGS]:
        """Devuelve el tipo de alerta a emitir, o ``None`` si no procede.

        Solo retorna no-``None`` en la *transición* hacia un nuevo evento crítico;
        una incidencia en curso (mismo tipo) se silencia hasta que se recupere.
        """
        raw = self._raw_event(proyecto_id, current_gen, expected_gen, now)
        if raw is None:
            self._active.pop(proyecto_id, None)
            return None
        if self._active.get(proyecto_id) == raw:
            return None  # incidencia en curso ya notificada
        self._active[proyecto_id] = raw
        return raw

    def rollback(self, proyecto_id: int) -> None:
        """Revierte el debounce de una transición que NO se pudo notificar.

        ``evaluate`` marca la incidencia como activa de forma optimista al
        detectar la transición; si la creación de la falla o la notificación
        fallan (catálogos/usuario ausentes, error transitorio de BD), esa marca
        silenciaría la alerta para siempre hasta una recuperación. Llamar a
        ``rollback`` reabre la ventana para que el próximo ciclo del scheduler
        reintente — así un fallo transitorio no descarta una alerta crítica.
        No toca ``_zero_since`` (la condición de cero sostenido sigue vigente)."""
        self._active.pop(proyecto_id, None)


# Instancia compartida usada por el job programado.
_detector = MGSCriticalDetector(
    drop_threshold=settings.MGS_PRODUCTION_DROP_THRESHOLD,
    disconnection_minutes=settings.MGS_DISCONNECTION_DURATION_MINUTES,
)

# Horario solar (Colombia) en el que tiene sentido evaluar generación.
SOLAR_START_HOUR = 6
SOLAR_END_HOUR = 18

_TIPO_ALERTA_LABEL = {
    TipoAlertaMGS.CAIDA_PRODUCCION: "Caída de producción crítica",
    TipoAlertaMGS.DESCONEXION_TOTAL: "Desconexión total",
}
_TIPO_ALERTA_SLA_HORAS = {
    TipoAlertaMGS.CAIDA_PRODUCCION: 24,
    TipoAlertaMGS.DESCONEXION_TOTAL: 8,
}


# ── Baseline esperado (lógica pura, testeable) ────────────────────────────────
def _solar_fraction_elapsed(now_dt: datetime) -> float:
    """Fracción [0,1] del horario solar (06:00–18:00) ya transcurrida.

    Fuera del horario solar devuelve 0 → no hay expectativa de generación y, por
    tanto, no se emiten alertas de noche."""
    start = now_dt.replace(hour=SOLAR_START_HOUR, minute=0, second=0, microsecond=0)
    end = now_dt.replace(hour=SOLAR_END_HOUR, minute=0, second=0, microsecond=0)
    if now_dt <= start or now_dt >= end:
        return 0.0
    return (now_dt - start).total_seconds() / (end - start).total_seconds()


def _expected_so_far_kwh(p50_mensual, now_dt: datetime, fraction: float) -> Optional[float]:
    """kWh esperados acumulados a esta hora, prorrateando el P50 mensual.

    ``p50_mensual`` es el arreglo de 12 valores (kWh/mes) almacenado en el
    proyecto. Devuelve ``None`` si no hay baseline utilizable."""
    if fraction <= 0 or not p50_mensual:
        return None
    try:
        arr = p50_mensual if isinstance(p50_mensual, list) else json.loads(p50_mensual)
        mensual = float(arr[now_dt.month - 1])
    except (ValueError, TypeError, IndexError, KeyError):
        return None
    if mensual <= 0:
        return None
    dias_mes = calendar.monthrange(now_dt.year, now_dt.month)[1]
    daily = mensual / dias_mes
    return round(daily * fraction, 3)


# ── Acceso a datos / construcción de falla + notificaciones ───────────────────
def _gather_plant_readings(db: Session) -> list[dict]:
    """Cruza el snapshot del scheduler MGS con los proyectos en operación (BD).

    Best-effort: ``current_gen`` son los kWh acumulados del día (eae) reportados
    por el monitoreo (0 si el medidor está sin datos/error); ``expected_gen`` es
    la generación esperada prorrateada por la fracción de horas solares. Mapea por
    nombre comercial / alias de monitoreo, igual que el resto del módulo MGS."""
    try:
        plants = scheduler.get_plants()
    except Exception:
        logger.exception("No se pudo obtener el snapshot de plantas MGS")
        return []
    if not plants:
        return []

    tz = pytz.timezone(settings.TIMEZONE)
    now_col = datetime.now(tz)
    fraction = _solar_fraction_elapsed(now_col)

    readings: list[dict] = []
    for p in plants:
        name = p.get("name")
        if not name:
            continue
        proy = db.execute(text("""
            SELECT id, nombre_comercial, p50_mensual_kwh
            FROM proyectos
            WHERE deleted_at IS NULL AND estado = 'en_operacion'
              AND (nombre_comercial = :name
                   OR alias_monitoreo ILIKE :pat
                   OR nombre_comercial ILIKE :pat)
            LIMIT 1
        """), {"name": name, "pat": f"%{name}%"}).mappings().first()
        if not proy:
            continue
        status = (p.get("status") or "").upper()
        current = 0.0 if status in ("NO_DATA", "ERROR") else float(p.get("kwh") or 0)
        expected = _expected_so_far_kwh(proy["p50_mensual_kwh"], now_col, fraction)
        readings.append({
            "proyecto_id": proy["id"],
            "nombre": proy["nombre_comercial"] or name,
            "current_gen": current,
            "expected_gen": expected,
        })
    return readings


def _operations_user_ids(db: Session) -> list[int]:
    """IDs de usuarios activos cuyos roles deben recibir las alertas críticas."""
    roles = [r for r in (settings.MGS_OPERATIONS_USER_ROLES or [])]
    if not roles:
        return []
    stmt = text("""
        SELECT id FROM usuarios
        WHERE activo = TRUE AND rol::text IN :roles
        ORDER BY id
    """).bindparams(bindparam("roles", expanding=True))
    rows = db.execute(stmt, {"roles": roles}).mappings().all()
    return [r["id"] for r in rows]


def _system_user_id(db: Session) -> Optional[int]:
    """Usuario al que se le atribuye el registro de la falla automática."""
    row = db.execute(text("""
        SELECT id FROM usuarios
        WHERE activo = TRUE AND rol::text IN ('admin', 'operaciones')
        ORDER BY id LIMIT 1
    """)).mappings().first()
    if not row:
        row = db.execute(text(
            "SELECT id FROM usuarios WHERE activo = TRUE ORDER BY id LIMIT 1"
        )).mappings().first()
    return row["id"] if row else None


def _has_open_mgs_falla(db: Session, proyecto_id: int, tipo: TipoAlertaMGS) -> bool:
    """¿Ya existe una falla MGS abierta para este proyecto + tipo de alerta?

    Evita duplicar la falla si el detector re-emite tras un reinicio del proceso."""
    row = db.execute(text("""
        SELECT f.id FROM fallas f
        JOIN fallas_cat_estados e ON f.estado_id = e.id
        WHERE f.proyecto_id = :pid
          AND f.origen = 'MGS_CRITICA'
          AND f.tipo_alerta_mgs = :ta
          AND e.es_estado_final = FALSE
          AND f.deleted_at IS NULL
        LIMIT 1
    """), {"pid": proyecto_id, "ta": tipo.value}).first()
    return row is not None


def _resolve_catalog_ids(db: Session) -> tuple[Optional[int], Optional[int]]:
    """(estado_id 'abierta', prioridad_id 'critica') con respaldos razonables."""
    estado = db.execute(text(
        "SELECT id FROM fallas_cat_estados WHERE codigo = 'abierta' LIMIT 1"
    )).mappings().first()
    if not estado:
        estado = db.execute(text(
            "SELECT id FROM fallas_cat_estados WHERE es_estado_final = FALSE ORDER BY orden LIMIT 1"
        )).mappings().first()
    prioridad = db.execute(text(
        "SELECT id FROM fallas_cat_prioridades WHERE codigo = 'critica' LIMIT 1"
    )).mappings().first()
    if not prioridad:
        prioridad = db.execute(text(
            "SELECT id FROM fallas_cat_prioridades ORDER BY nivel LIMIT 1"
        )).mappings().first()
    return (estado["id"] if estado else None, prioridad["id"] if prioridad else None)


def _descripcion_evento(tipo: TipoAlertaMGS, reading: dict) -> str:
    nombre = reading.get("nombre") or f"Proyecto {reading['proyecto_id']}"
    cur = reading.get("current_gen")
    exp = reading.get("expected_gen")
    if tipo == TipoAlertaMGS.DESCONEXION_TOTAL:
        return (f"[MGS] Desconexión total en {nombre}: generación sostenida en 0 "
                f"durante el horario solar (esperado ~{exp} kWh).")
    return (f"[MGS] Caída de producción crítica en {nombre}: generación "
            f"{cur} kWh frente a ~{exp} kWh esperados.")


def _create_falla_for_event(
    db: Session, reading: dict, tipo: TipoAlertaMGS, now: datetime,
):
    """Crea la falla MGS_CRITICA reutilizando ``_create_falla_internal``."""
    from app.api.v1.fallas import _create_falla_internal
    from app.schemas.fallas import FallaCreate

    estado_id, prioridad_id = _resolve_catalog_ids(db)
    reg_id = _system_user_id(db)
    if not estado_id or not prioridad_id or not reg_id:
        logger.warning(
            "No se puede crear falla MGS (proyecto %s): faltan catálogos o usuario",
            reading.get("proyecto_id"),
        )
        return None

    data = FallaCreate(
        proyecto_id=reading["proyecto_id"],
        tipo_id=None,
        tipo_libre=f"MGS · {_TIPO_ALERTA_LABEL[tipo]}",
        estado_id=estado_id,
        prioridad_id=prioridad_id,
        descripcion=_descripcion_evento(tipo, reading),
        fecha_identificacion=now.date(),
        sla_limite_horas=_TIPO_ALERTA_SLA_HORAS[tipo],
        centinela="MGS_CRITICA",
        notificacion=True,
        origen=OrigenFalla.MGS_CRITICA,
        tipo_alerta_mgs=tipo,
    )
    return _create_falla_internal(db, data, reg_id)


def _notify_ops_users(db: Session, reading: dict, tipo: TipoAlertaMGS, url: str, falla) -> int:
    """Notifica in-app ('Alerta Crítica') a los usuarios de operaciones. Devuelve
    cuántas notificaciones se crearon."""
    from app.api.v1.notificaciones import crear_notificacion

    user_ids = _operations_user_ids(db)
    if not user_ids:
        logger.warning("No hay usuarios de operaciones para notificar (roles=%s)",
                       settings.MGS_OPERATIONS_USER_ROLES)
        return 0
    nombre = reading.get("nombre") or f"Proyecto {reading['proyecto_id']}"
    mensaje = f"{_TIPO_ALERTA_LABEL[tipo]} en {nombre} ({falla.codigo_interno}). Revisar incidencia."
    for uid in user_ids:
        crear_notificacion(
            db=db, usuario_id=uid, tipo="alerta",
            titulo="Alerta Crítica", mensaje=mensaje, link=url,
        )
    db.commit()
    return len(user_ids)


def check_mgs_critical_events(
    db: Session, readings: Optional[list[dict]] = None, now: Optional[datetime] = None,
) -> list[int]:
    """Detecta eventos críticos del MGS y genera fallas + notificaciones.

    Para cada proyecto monitoreado compara la generación actual con la esperada;
    si detecta caída de producción crítica o desconexión total (con debounce),
    crea una falla ``origen=MGS_CRITICA`` y notifica in-app a operaciones con un
    enlace al detalle de la falla. ``readings``/``now`` son inyectables para test.
    Devuelve los IDs de las fallas creadas en esta corrida."""
    now = now or datetime.now(timezone.utc)
    if readings is None:
        readings = _gather_plant_readings(db)

    creadas: list[int] = []
    for r in readings:
        pid = r.get("proyecto_id")
        try:
            tipo = _detector.evaluate(pid, r.get("current_gen"), r.get("expected_gen"), now)
            if tipo is None:
                continue
            if _has_open_mgs_falla(db, pid, tipo):
                logger.debug("Falla MGS abierta ya existe para proyecto %s / %s — omitida",
                             pid, tipo.value)
                continue
            falla = _create_falla_for_event(db, r, tipo, now)
            if falla is None:
                # No se pudo crear (catálogos/usuario ausentes): reabre el
                # debounce para reintentar en el próximo ciclo en vez de
                # silenciar la alerta de forma permanente.
                _detector.rollback(pid)
                continue
            url = f"/app/fallas/{falla.id}"
            _notify_ops_users(db, r, tipo, url, falla)
            creadas.append(falla.id)
            logger.info("Evento crítico MGS: falla %s creada (proyecto %s, %s)",
                        falla.codigo_interno, pid, tipo.value)
        except Exception:
            db.rollback()
            # Error transitorio: reabre el debounce para reintentar. La falla la
            # crea ``_create_falla_internal`` en su propia transacción, así que
            # ``_has_open_mgs_falla`` evita duplicarla si llegó a persistirse.
            _detector.rollback(pid)
            logger.exception("check_mgs_critical_events: error procesando proyecto %s", pid)

    return creadas


def run_mgs_critical_events_check() -> None:
    """Punto de entrada para el scheduler: abre su propia sesión y corre el chequeo."""
    if not settings.MGS_ENABLED:
        return
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        ids = check_mgs_critical_events(db)
        if ids:
            logger.info("check_mgs_critical_events: %d falla(s) crítica(s) creada(s)", len(ids))
    except Exception:
        db.rollback()
        logger.exception("run_mgs_critical_events_check falló")
    finally:
        db.close()


@router.get("/status")
def mgs_status(_=Depends(get_current_user)):
    return scheduler.get_status()


@router.get("/plants")
def mgs_plants(_=Depends(get_current_user)):
    return scheduler.get_plants()


@router.get("/plants/{name}")
def mgs_plant_detail(name: str, _=Depends(get_current_user)):
    plants = scheduler.get_plants()
    for p in plants:
        if p["name"] == name:
            return p
    return {"error": "Proyecto no encontrado"}


@router.get("/alarms")
def mgs_alarms(
    severity: str | None = Query(None),
    alarm_type: str | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = """
        SELECT id, proyecto_nombre, severity, alarm_type, details,
               source_data, resolved_at, created_at
        FROM alarmas_monitoreo
        WHERE resolved_at IS NULL
    """
    params: dict = {}
    if severity:
        q += " AND severity = :severity"
        params["severity"] = severity
    if alarm_type:
        q += " AND alarm_type = :alarm_type"
        params["alarm_type"] = alarm_type
    q += " ORDER BY created_at DESC LIMIT 100"

    rows = db.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows]


@router.get("/alarms/history")
def mgs_alarms_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    offset = (page - 1) * page_size
    rows = db.execute(text("""
        SELECT id, proyecto_nombre, severity, alarm_type, details,
               resolved_at, created_at
        FROM alarmas_monitoreo
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), {"limit": page_size, "offset": offset}).mappings().all()

    total = db.execute(text("SELECT COUNT(*) FROM alarmas_monitoreo")).scalar()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/alarms/{alarm_id}/resolve")
def mgs_resolve_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    result = db.execute(
        text("""
            UPDATE alarmas_monitoreo
            SET resolved_at = NOW()
            WHERE id = :id AND resolved_at IS NULL
            RETURNING id, proyecto_nombre, alarm_type
        """),
        {"id": alarm_id},
    ).mappings().first()
    db.commit()
    if not result:
        return {"error": "Alarma no encontrada o ya resuelta"}
    return {"status": "resolved", "alarm": dict(result)}


@router.patch("/alarms/resolve-all")
def mgs_resolve_all(
    severity: str | None = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = "UPDATE alarmas_monitoreo SET resolved_at = NOW() WHERE resolved_at IS NULL"
    params: dict = {}
    if severity:
        q += " AND severity = :severity"
        params["severity"] = severity
    result = db.execute(text(q), params)
    db.commit()
    return {"status": "resolved", "count": result.rowcount}


@router.post("/poll")
def mgs_force_poll(_=Depends(get_current_user)):
    started = scheduler.poll_once_async()
    if started:
        return {"status": "poll_started"}
    return {"status": "poll_already_running"}
