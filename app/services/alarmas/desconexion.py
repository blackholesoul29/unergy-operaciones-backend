"""Alarmas de desconexión / fuentes de medición.

Evalúa cada proyecto monitoreado comparando sus dos fuentes (inversores Solenium vs
medidor Gaia) y notifica vía el sistema in-app (campana) cuando detecta:
  - FUENTE_UNICA        → el proyecto no tiene medidor configurado (no se puede cruzar)
  - SIN_DATOS           → de día, ambas fuentes en 0 / sin datos
  - POSIBLE_DESCONEXION → de día, una fuente genera y la otra en 0 (peligro)
  - RECUPERACION        → vuelve a reportar normal tras una alarma

Anti-spam: notifica solo en cambios de estado; re-notifica una vez al día si persiste.
Corre dentro del ciclo de 15 min del scheduler MGS (Railway). No re-implementa la
lógica de monitoreo: reutiliza los clientes Solenium/Gaia ya existentes.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from app.core.database import SessionLocal
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.usuarios import Usuario, RolEnum
from app.models.notificaciones import Notificacion, TipoNotificacionEnum
from app.services.mgs.solenium_client import SoleniumClient
from app.services.mgs.gaia_client import GaiaClient, find_gaia_node_pair, build_db_proyecto_frt_map

logger = logging.getLogger("alarmas.desconexion")

# ── Parámetros ajustables ─────────────────────────────────────────────────────
ZERO_KW = 0.5        # potencia <= esto se considera "en cero"
DAY_START_H = 7      # ventana de día (Colombia) para evaluar desconexión
DAY_END_H = 17
ROLES_NOTIF = (RolEnum.admin, RolEnum.operaciones, RolEnum.monitoreo)


def _col_now() -> datetime:
    """Ahora en hora Colombia (UTC-5, sin DST)."""
    return datetime.now(timezone.utc) - timedelta(hours=5)


def _is_daylight() -> bool:
    return DAY_START_H <= _col_now().hour < DAY_END_H


def _latest_meter_kw(snap: dict | None) -> float | None:
    """Potencia actual del medidor (kW) = último punto de la serie de potencia."""
    if not snap:
        return None
    series = (snap.get("time_series") or {}).get("power") or []
    for pt in reversed(series):
        kw = pt.get("kw")
        if kw is not None:
            return abs(float(kw))
    return None


# ── Notificaciones in-app (campana) ───────────────────────────────────────────
def _notificar(db, tipo: TipoNotificacionEnum, titulo: str, mensaje: str, link: str | None):
    usuarios = db.query(Usuario).filter(
        Usuario.activo == True,  # noqa: E712
        Usuario.rol.in_(list(ROLES_NOTIF)),
    ).all()
    for u in usuarios:
        db.add(Notificacion(usuario_id=u.id, tipo=tipo, titulo=titulo, mensaje=mensaje, link=link))


_MENSAJES = {
    "fuente_unica": (
        TipoNotificacionEnum.alerta, "Fuente única de medición",
        "{n} solo tiene inversores (sin medidor configurado) — no se puede cruzar inversores vs medidor.",
    ),
    "sin_datos": (
        TipoNotificacionEnum.alerta, "Proyecto sin datos",
        "{n}: ni inversores ni medidor reportan generación de día (posible desconexión).",
    ),
    "posible_desconexion": (
        TipoNotificacionEnum.alerta, "⚠️ Posible desconexión",
        "{n}: una fuente genera y la otra está en 0 (inversores {inv} kW / medidor {met} kW). Revisar.",
    ),
}


def _procesar(db, proyecto: Proyecto, categoria: str, estado_nuevo: str, ctx: dict):
    """Compara con el estado guardado y notifica según cambios + re-aviso diario."""
    today = _col_now().date()
    row = db.execute(
        text("SELECT estado, dia FROM alarma_estado WHERE proyecto_id=:p AND categoria=:c"),
        {"p": proyecto.id, "c": categoria},
    ).fetchone()

    notify = False
    recovery = False
    if row is None:
        notify = estado_nuevo != "ok"
    elif row.estado != estado_nuevo:
        notify = True
        recovery = estado_nuevo == "ok"
    elif estado_nuevo != "ok" and (row.dia is None or row.dia < today):
        notify = True  # re-aviso diario

    if not notify:
        return

    dia_val = today if estado_nuevo != "ok" else None
    db.execute(text("""
        INSERT INTO alarma_estado (proyecto_id, categoria, estado, dia, updated_at)
        VALUES (:p, :c, :e, :d, now())
        ON CONFLICT (proyecto_id, categoria)
        DO UPDATE SET estado = :e, dia = :d, updated_at = now()
    """), {"p": proyecto.id, "c": categoria, "e": estado_nuevo, "d": dia_val})

    link = f"/proyectos/{proyecto.id}"
    nombre = proyecto.nombre_comercial or f"Proyecto {proyecto.id}"
    if recovery:
        _notificar(db, TipoNotificacionEnum.info, "Proyecto recuperado",
                   f"{nombre} volvió a reportar normal.", link)
    else:
        tipo, titulo, plantilla = _MENSAJES[estado_nuevo]
        mensaje = plantilla.format(n=nombre, inv=ctx.get("inv", "—"), met=ctx.get("met", "—"))
        _notificar(db, tipo, titulo, mensaje, link)


# ── Entrada principal ─────────────────────────────────────────────────────────
def evaluar_desconexiones():
    """Evalúa todos los proyectos monitoreados y emite notificaciones. Idempotente."""
    sol = SoleniumClient()
    if not sol.enabled:
        logger.info("Solenium no configurado — alarmas de desconexión omitidas")
        return

    db = SessionLocal()
    try:
        proyectos = db.query(Proyecto).filter(
            Proyecto.estado == "en_operacion",
            Proyecto.project_id_solenium.isnot(None),
            Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
            Proyecto.srv_operacion == True,  # noqa: E712
        ).all()
        if not proyectos:
            return

        # Inversores: 2 llamadas de flota
        avail_map = sol.get_availability() or {}
        summary_list = sol.get_project_summary() or []
        if not avail_map and not summary_list:
            logger.warning("Solenium devolvió vacío — se omite evaluación (evita falsas alarmas)")
            return
        summary_map = {}
        for s in summary_list:
            pid = s.get("project_id") or s.get("id")
            if pid is not None:
                summary_map[int(pid)] = s

        gaia = GaiaClient()
        daylight = _is_daylight()

        # Vínculo directo fronteras.proyecto_id -> codigo_frontera (fuente de verdad
        # reconciliada, ver scripts/etl_fronteras_proyectos.py). Evita adivinar por
        # nombre para la gran mayoría de los proyectos.
        _db_fronteras = db.query(Frontera.proyecto_id, Frontera.codigo_frontera).filter(
            Frontera.tipo_frontera.in_([TipoFronteraEnum.generacion, TipoFronteraEnum.generacion_consumo]),
            Frontera.codigo_frontera.isnot(None),
        ).all()
        _db_proyecto_frt_map = build_db_proyecto_frt_map(list(_db_fronteras))

        # Resolver medidor (vínculo directo en BD, sin red) y traer snapshots en paralelo
        node_pairs = {}
        for p in proyectos:
            node_pairs[p.id] = find_gaia_node_pair(
                proyecto_id=p.id, db_proyecto_frt_map=_db_proyecto_frt_map,
            )

        snap_map: dict[int, dict | None] = {}
        if gaia and gaia.enabled:
            def _snap(p):
                node_p, node_r = node_pairs[p.id]
                node = node_p or node_r
                if not node:
                    return p.id, None
                try:
                    return p.id, gaia.get_node_electrical_snapshot(node)
                except Exception:
                    return p.id, "ERROR"  # distinguir fallo de red de "sin medidor"
            with ThreadPoolExecutor(max_workers=6) as ex:
                for pid, snap in ex.map(_snap, proyectos):
                    snap_map[pid] = snap

        for p in proyectos:
            try:
                sol_id = int(p.project_id_solenium)
                node_p, node_r = node_pairs[p.id]
                meter_present = bool(node_p or node_r)

                # ── Dimensión config: fuente única ──────────────────────────────
                _procesar(db, p, "fuente", "fuente_unica" if not meter_present else "ok", {})

                # ── Dimensión runtime: solo de día y con ambas fuentes ──────────
                if not daylight or not meter_present:
                    continue
                # inversores: requiere dato conocido de Solenium para este proyecto
                if sol_id not in avail_map and sol_id not in summary_map:
                    continue
                cat = (avail_map.get(sol_id) or {}).get("category")
                inv_power = float((summary_map.get(sol_id) or {}).get("power_kw") or 0)
                inv_has = cat != "disconnect" and inv_power > ZERO_KW

                snap = snap_map.get(p.id)
                if snap == "ERROR":
                    continue  # fallo de red Gaia → no evaluar runtime este ciclo
                met_kw = _latest_meter_kw(snap)
                met_has = met_kw is not None and met_kw > ZERO_KW

                if not inv_has and not met_has:
                    estado = "sin_datos"
                elif inv_has != met_has:
                    estado = "posible_desconexion"
                else:
                    estado = "ok"

                _procesar(db, p, "runtime", estado, {
                    "inv": round(inv_power, 1),
                    "met": round(met_kw, 1) if met_kw is not None else 0,
                })
            except Exception:
                logger.exception("Error evaluando proyecto %s", p.id)

        db.commit()
        logger.info("Alarmas de desconexión evaluadas: %d proyectos", len(proyectos))
    except Exception:
        db.rollback()
        logger.exception("evaluar_desconexiones falló")
    finally:
        db.close()
