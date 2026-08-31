"""Alarmas de desconexión / fuentes de medición.

Evalúa cada proyecto monitoreado comparando sus dos fuentes (inversores SolarView vs
medidor Gaia) y notifica vía el sistema in-app (campana) cuando detecta:
  - FUENTE_UNICA        → el proyecto no tiene medidor configurado (no se puede cruzar)
  - SIN_DATOS           → de día, ambas fuentes en 0 / sin datos
  - POSIBLE_DESCONEXION → de día, una fuente genera y la otra en 0 (peligro)
  - RECUPERACION        → vuelve a reportar normal tras una alarma

Anti-spam: notifica solo en cambios de estado; re-notifica una vez al día si persiste.
Corre dentro del ciclo de 15 min del scheduler MGS (Railway). No re-implementa la
lógica de monitoreo: reutiliza los clientes SolarView/Gaia ya existentes.

Migrado de Solenium a SolarView (Fase 2 de la migración -- Fase 1 fue Reporte de
Energía, ver commit c417d30). `avail_map` viene de GET /solarview/kpis/availability/,
que sí trae toda la flota en una sola llamada con la categoría `disconnect` ya
calculada (equivalente exacto a SoleniumClient.get_availability()) -- a diferencia
de la potencia instantánea, que SolarView solo expone por proyecto
(GET /solarview/measurements/power/), así que esa parte sigue necesitando una
llamada por proyecto (en paralelo, mismo patrón que ya usa Gaia acá abajo), y
solo para los proyectos que de verdad la necesitan (de día + con medidor).

El anti-spam contra alarma_estado y el envío de notificaciones viven en
app.services.alarmas.estado, compartido con fallas/alarmas.py."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

from app.core.database import SessionLocal
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.notificaciones import TipoNotificacionEnum
from app.services.alarmas.estado import (
    cargar_estados, decidir_notificar, guardar_estados, usuarios_notificables, notificar,
)
from app.services.mgs.solarview_client import SolarViewClient
from app.services.mgs.gaia_client import GaiaClient, find_gaia_node_pair, build_db_proyecto_frt_map

logger = logging.getLogger("alarmas.desconexion")

# ── Parámetros ajustables ─────────────────────────────────────────────────────
ZERO_KW = 0.5        # potencia <= esto se considera "en cero"
DAY_START_H = 7      # ventana de día (Colombia) para evaluar desconexión
DAY_END_H = 17


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


def _latest_inverter_kw(resp: dict | None) -> float | None:
    """Potencia actual de inversores (kW) = último punto de
    GET /solarview/measurements/power/ (total_power=1 -- ya viene sumada entre
    todos los inversores del proyecto, ver SolarViewClient.get_power)."""
    if not resp:
        return None
    serie = (resp.get("results") or {}).get("power") or {}
    if not serie:
        return None
    ultimo_ts = max(serie.keys())
    valor = serie.get(ultimo_ts)
    return abs(float(valor)) if valor is not None else None


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


def _procesar(cache, pending_writes: list[dict], usuarios, db,
              proyecto: Proyecto, categoria: str, estado_nuevo: str, ctx: dict):
    """Envoltorio delgado sobre estado.decidir_notificar(): sabe qué mensaje
    corresponde a cada estado de desconexión (`_MENSAJES`) y arma el texto;
    la decisión de si toca notificar y el UPSERT masivo viven en el módulo
    compartido (ver import)."""
    hoy = _col_now().date()
    notify, recovery = decidir_notificar(cache, pending_writes, proyecto.id, categoria, estado_nuevo, hoy)
    if not notify:
        return

    nombre = proyecto.nombre_comercial or f"Proyecto {proyecto.id}"
    if recovery:
        notificar(db, usuarios, TipoNotificacionEnum.info, "Proyecto recuperado",
                  f"{nombre} volvió a reportar normal.")
    else:
        tipo, titulo, plantilla = _MENSAJES[estado_nuevo]
        mensaje = plantilla.format(n=nombre, inv=ctx.get("inv", "—"), met=ctx.get("met", "—"))
        notificar(db, usuarios, tipo, titulo, mensaje)


# ── Entrada principal ─────────────────────────────────────────────────────────
def evaluar_desconexiones():
    """Evalúa todos los proyectos monitoreados y emite notificaciones. Idempotente."""
    sv = SolarViewClient()
    if not sv.enabled:
        logger.info("SolarView no configurado — alarmas de desconexión omitidas")
        return

    db = SessionLocal()
    try:
        proyectos = db.query(Proyecto).filter(
            Proyecto.estado == "en_operacion",
            Proyecto.project_id_solarview.isnot(None),
            Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
            Proyecto.srv_operacion == True,  # noqa: E712
        ).all()
        if not proyectos:
            return

        # Precarga de alarma_estado: un solo SELECT para todos los proyectos
        # de este ciclo (ver app.services.alarmas.estado) en vez de uno por
        # (proyecto, categoria) dentro de _procesar().
        cache = cargar_estados(db, [p.id for p in proyectos])
        pending_writes: list[dict] = []
        usuarios = usuarios_notificables(db)

        # Inversores: disponibilidad de TODA la flota en una sola llamada
        # (GET /solarview/kpis/availability/, ya trae la categoria
        # 'disconnect' calculada -- ver SolarViewClient.get_availability).
        avail_map = sv.get_availability() or {}
        if not avail_map:
            logger.warning("SolarView devolvió vacío — se omite evaluación (evita falsas alarmas)")
            return

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

        # Potencia instantánea de inversores: SolarView solo la expone por
        # proyecto (GET /solarview/measurements/power/), a diferencia de
        # get_availability(). Se pide en paralelo (mismo patrón que Gaia
        # arriba) y solo para los proyectos que de verdad la van a usar
        # (de día + con medidor vinculado) -- evita llamadas de sobra los
        # ciclos nocturnos o en proyectos sin medidor que igual seguirían
        # de largo más abajo.
        power_map: dict[int, dict | None] = {}
        if daylight:
            hoy_str = _col_now().strftime("%Y-%m-%d")
            proyectos_runtime = [
                p for p in proyectos
                if bool(node_pairs[p.id][0] or node_pairs[p.id][1]) and p.project_id_solarview
            ]

            def _power(p):
                try:
                    return p.id, sv.get_power(int(p.project_id_solarview), hoy_str, hoy_str)
                except Exception:
                    return p.id, "ERROR"
            with ThreadPoolExecutor(max_workers=6) as ex:
                for pid, resp in ex.map(_power, proyectos_runtime):
                    power_map[pid] = resp

        for p in proyectos:
            try:
                sv_id = int(p.project_id_solarview)
                node_p, node_r = node_pairs[p.id]
                meter_present = bool(node_p or node_r)

                # ── Dimensión config: fuente única ──────────────────────────────
                _procesar(cache, pending_writes, usuarios, db, p,
                          "fuente", "fuente_unica" if not meter_present else "ok", {})

                # ── Dimensión runtime: solo de día y con ambas fuentes ──────────
                if not daylight or not meter_present:
                    continue
                # inversores: requiere dato conocido de SolarView para este proyecto
                if sv_id not in avail_map:
                    continue
                cat = (avail_map.get(sv_id) or {}).get("category")
                power_resp = power_map.get(p.id)
                if power_resp == "ERROR":
                    continue  # fallo de red SolarView → no evaluar runtime este ciclo
                inv_power = _latest_inverter_kw(power_resp) or 0.0
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

                _procesar(cache, pending_writes, usuarios, db, p, "runtime", estado, {
                    "inv": round(inv_power, 1),
                    "met": round(met_kw, 1) if met_kw is not None else 0,
                })
            except Exception:
                logger.exception("Error evaluando proyecto %s", p.id)

        guardar_estados(db, pending_writes)
        db.commit()
        logger.info("Alarmas de desconexión evaluadas: %d proyectos", len(proyectos))
    except Exception:
        db.rollback()
        logger.exception("evaluar_desconexiones falló")
    finally:
        db.close()
