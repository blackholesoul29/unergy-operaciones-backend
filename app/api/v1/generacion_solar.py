"""Generación solar en tiempo real, desde la API de inversores de SolarView.

Migrado de Solenium el 2026-09-03. Los ids de los dos proveedores son
esquemas DISTINTOS que no se derivan uno del otro, así que la resolución va
por `Proyecto.project_id_solarview`, reconciliado por el equipo y poblado por
services/proyectos_backfill_solarview.py.

A propósito NO se empareja por nombre. Antes, si a un proyecto le faltaba el
id, se buscaba en el catálogo del proveedor por coincidencia de nombre --
exacta primero y luego por subcadena de ≥ 5 caracteres-- y el resultado se
persistía como efecto secundario de un GET. Eso es una adivinanza silenciosa
que se recalcula en cada request y puede cambiar de respuesta si el proveedor
renombra algo. El mismo criterio que sigue Reporte de Energía: un proyecto sin
id reconciliado no tiene inversores, y el hueco queda visible para que lo
resuelva el backfill.
"""
from __future__ import annotations

import calendar
import logging
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.services.mgs.medidor_tiempo_real import elegir_medidor, snapshot_medidor
from app.services.mgs.gaia_client import (
    GaiaClient, build_db_proyecto_frt_map,
    find_gaia_node_id, find_gaia_node_pair,
)
from app.services.mgs.solarview_client import SolarViewClient
from app.services.reporte_energia.utils import limite_plausible_kwh

logger = logging.getLogger("generacion_solar")
router = APIRouter(prefix="/generacion-solar", tags=["Generación Solar"])

# Colombia opera en America/Bogota = UTC-5 (sin horario de verano). El servidor
# de producción (Railway) corre en UTC, por lo que `_hoy_col()` devuelve la
# fecha UTC y "hoy" se adelanta 5h: entre las 19:00 y medianoche de Bogotá el
# servidor ya está en el día siguiente y la "generación de hoy" salía casi en
# cero. Las claves de franja horaria de Solenium están en hora local de la
# planta (Bogotá), así que el día con el que se filtran/cachean debe ser el de
# Bogotá. Ver _COL_TZ usado igual en fallas.py / cumplimiento.py / desconexion.py.
_COL_TZ = timezone(timedelta(hours=-5))


def _hoy_col() -> date:
    """Fecha actual en hora de Colombia (Bogotá, UTC-5), independiente del TZ del servidor."""
    return datetime.now(_COL_TZ).date()

_client: SolarViewClient | None = None
_gaia_client: GaiaClient | None = None

# ── TTL cache en memoria ───────────────────────────────────────────────────────
# Evita llamar a Solenium/Gaia en cada request; se invalida solo pasado el TTL.
_cache: dict[str, tuple[float, object]] = {}   # key → (timestamp, data)

CACHE_TTL_FLEET  = 60    # segundos — fleet monitoring (datos de flota)
CACHE_TTL_DETAIL = 90    # segundos — detalle por proyecto
CACHE_TTL_GENHOY = 120   # segundos — generación de hoy


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry[0] < entry[1][0]:  # type: ignore[index]
        return entry[1][1]
    return None


def _cache_set(key: str, ttl: int, data: object) -> None:
    _cache[key] = (time.monotonic(), (ttl, data))


def _get_client() -> SolarViewClient:
    global _client
    if _client is None:
        _client = SolarViewClient()
    if not _client.enabled:
        raise HTTPException(503, "SolarView credentials not configured")
    return _client


def _sv_id(p: Proyecto) -> int | None:
    """El id de SolarView del proyecto, o None si no está reconciliado.

    Sin fallback por nombre a propósito -- ver el docstring del módulo.
    """
    if not p.project_id_solarview:
        return None
    try:
        return int(p.project_id_solarview)
    except (TypeError, ValueError):
        logger.warning("project_id_solarview inválido proyecto_id=%s valor=%r",
                       p.id, p.project_id_solarview)
        return None


def _get_gaia() -> GaiaClient | None:
    """Returns the GaiaClient if credentials are configured, else None (non-fatal)."""
    global _gaia_client
    if _gaia_client is None:
        _gaia_client = GaiaClient()
    return _gaia_client if _gaia_client.enabled else None


def _limite_hora_kwh(capacidad_kwp: float | None) -> float | None:
    """Techo de kWh en una hora para una planta, o None si no se sabe su
    capacidad. Reusa el mismo criterio del pipeline del ASIC."""
    if not capacidad_kwp or capacidad_kwp <= 0:
        return None
    return limite_plausible_kwh(float(capacidad_kwp) / 1000)


def _es_hora_plausible(valor, limite: float | None) -> bool:
    """Si esa hora de generacion es fisicamente posible para la planta."""
    try:
        val = float(valor)
    except (TypeError, ValueError):
        return False
    return limite is None or abs(val) <= limite


def _sum_today_inverter_kwh(gen_kwh_map: dict, today_str: str,
                            capacidad_kwp: float | None = None) -> float:
    """Suma las entradas de HOY de un mapa generation_kwh de SolarView.

    `get_generation(ayer, hoy)` devuelve valores incrementales por franja horaria
    con claves tipo "2026-06-09 08:00"; nos quedamos solo con las de hoy.

    Se descartan las horas fisicamente imposibles. SolarView calcula la
    generacion POR DIFERENCIA DE ACUMULADOS, asi que cuando el acumulador se
    reinicia o falla, la diferencia es el acumulado historico entero. Verificado
    en vivo el 2026-09-03 con San Pedro (996 kWp): dos horas del dia marcaban
    4.682.690,23 kWh cada una, junto a valores normales de 87,52 kWh. Sin este
    filtro el total del dia daba 4,7 GWh y el de la flota 98 GWh.

    Es el mismo glitch y el mismo guardia que ya usa
    reporte_energia/solarview.py::curva_generacion (ver MGS 0010 Villanueva
    2026-08-26, ~48.090 kWh en una hora para 0,99 MW)."""
    if not gen_kwh_map:
        return 0.0
    limite = _limite_hora_kwh(capacidad_kwp)
    total = 0.0
    for k, v in gen_kwh_map.items():
        if not str(k).startswith(today_str):
            continue
        if not _es_hora_plausible(v, limite):
            logger.warning("hora descartada: %s = %r (techo %s)", k, v, limite)
            continue
        total += float(v)
    return total


def _meter_kwh_from_detail(detail: dict | None) -> float | None:
    """Energía del día del medidor (frontera) desde /config/project-detail/.

    Reemplaza al `frontier_generation_kwh` del lote de summary de Solenium, que
    SolarView no tiene. La unidad viene DECLARADA en el propio bloque y puede
    ser kWh o MWh -- verificado en vivo el 2026-09-03: {"time":..., "value":...,
    "unit":"kWh", "complete":...}. Se lee, nunca se asume.
    """
    if not detail:
        return None
    if "results" in detail:
        detail = detail["results"]
    gen = (detail or {}).get("generation") or {}
    if not gen.get("value"):
        return None
    try:
        val = float(gen["value"])
    except (ValueError, TypeError):
        return None
    unit = (gen.get("unit") or "kWh").strip().lower()
    return val * 1000 if unit == "mwh" else val


@router.get("/proyecto/{proyecto_id}/historial")
def proyecto_historial(
    proyecto_id: int,
    fecha_inicio: str = Query(..., description="YYYY-MM-DD"),
    fecha_fin: str = Query(..., description="YYYY-MM-DD"),
    granularidad: str = Query("day", description="day | hour"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Generación histórica de un proyecto desde Solenium.

    Acepta el ID interno de nuestra BD y resuelve el Solenium project_id
    usando project_id_solarview. Devuelve puntos diarios u horarios.

    Respuesta:
      {
        proyecto_id, nombre, sol_id,
        granularidad,           # 'day' | 'hour'
        puntos: [{ label, kwh }],
        total_kwh
      }
    """
    # 1. Buscar proyecto en nuestra BD
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")

    # 2. Resolver el id de SolarView
    sol_id = _sv_id(p)
    if sol_id is None:
        raise HTTPException(
            404,
            "Este proyecto no tiene ID en SolarView. Se asigna con el backfill "
            "(services/proyectos_backfill_solarview.py) o a mano en project_id_solarview.",
        )

    # 3. Generación desde SolarView
    client = _get_client()
    raw = client.get_generation(sol_id, fecha_inicio, fecha_fin) or {}

    # La generación viene en generation_kwh: {"2026-05-22 08:00": 123.4, ...}
    gen_kwh: dict[str, float] = raw.get("generation_kwh") or {}

    if granularidad == "hour":
        # Devolver cada punto horario directamente
        puntos = [
            {"label": ts, "kwh": round(float(v), 2)}
            for ts, v in sorted(gen_kwh.items())
        ]
    else:
        # Agregar por día: sumar todas las horas del mismo día
        daily: dict[str, float] = {}
        for ts, v in gen_kwh.items():
            day = ts.split(" ")[0]       # "2026-05-22 08:00" → "2026-05-22"
            daily[day] = daily.get(day, 0.0) + float(v)
        puntos = [
            {"label": day, "kwh": round(kwh, 1)}
            for day, kwh in sorted(daily.items())
        ]

    total_kwh = round(sum(pt["kwh"] for pt in puntos), 1)

    return {
        "proyecto_id": p.id,
        "nombre":      p.nombre_comercial,
        "sol_id":      sol_id,
        "granularidad": granularidad,
        "puntos":      puntos,
        "total_kwh":   total_kwh,
    }


@router.get("/generacion-hoy")
def generacion_hoy(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Generación real de HOY por proyecto, desde SolarView.
    Resuelve por project_id_solarview; un proyecto sin ese id no aparece.
    Devuelve proyecto_id, nombre y kwh_real para los gráficos de Monitoreo.
    """
    _GENHOY_KEY = f"genhoy:{_hoy_col().isoformat()}"
    cached = _cache_get(_GENHOY_KEY)
    if cached:
        return cached

    client = _get_client()

    proyectos_db = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
    ).all()

    # (proyecto, sol_id). Ya no hay `summary`: SolarView no tiene un lote de
    # potencia de flota, y `power_kw` no lo lee nadie -- su unico consumidor era
    # GeneracionSolarView.vue, que se borro por estar muerta (2026-09-03).
    matched: list[tuple] = []
    for p in proyectos_db:
        sol_id = _sv_id(p)
        if sol_id is None:
            logger.debug("sin id de solarview: proyecto_id=%d nombre='%s'", p.id, p.nombre_comercial)
            continue
        matched.append((p, sol_id))

    logger.info("proyectos con id de solarview: %d / %d", len(matched), len(proyectos_db))

    # 5. Obtener kwh_real e indicador de fuente por proyecto
    #    Fuentes posibles:
    #    - "inversor"  → /project/{id}/generation/ → total_generation_kwh (kWh, datos de inversores)
    #    - "medidor"   → /project_detail/{id}/ → generation.value en MWh (medidor de frontera)
    #    - "sin_dato"  → ninguna fuente disponible
    today_str = _hoy_col().isoformat()

    def _fetch_kwh(item: tuple) -> tuple:
        p, sol_id = item
        kwh = 0.0
        fuente = "sin_dato"

        # Fuente 1: get_generation(ayer, hoy) → filtramos solo entradas de hoy.
        # Llamar con un solo día devuelve el acumulado histórico; con rango ayer→hoy
        # devuelve valores incrementales por franja horaria y filtramos las de hoy.
        try:
            from datetime import timedelta
            yesterday_str = (_hoy_col() - timedelta(days=1)).isoformat()
            gen = client.get_generation(sol_id, yesterday_str, today_str) or {}
            if "results" in gen:
                gen = gen["results"]
            kwh = _sum_today_inverter_kwh(gen.get("generation_kwh") or {}, today_str,
                                          p.potencia_instalada_kwp)
            if kwh > 0:
                fuente = "inversor"
        except Exception as exc:
            logger.warning("generation fallo sol_id=%d: %s", sol_id, exc)

        # Fuente 2: project_detail → generation.value en MWh (medidor de frontera)
        if kwh == 0.0:
            try:
                detail = client.get_project_detail(sol_id) or {}
                if "results" in detail:
                    detail = detail["results"]
                gen_detail = detail.get("generation") or {}
                if gen_detail and gen_detail.get("value"):
                    # La unidad viene declarada en el propio bloque y puede ser
                    # kWh o MWh -- verificado en vivo contra SolarView el
                    # 2026-09-03: {"time":..., "value":..., "unit":"kWh",
                    # "complete":...}. Se lee, no se asume, y la comparacion es
                    # en minusculas porque la etiqueta varia de mayusculas.
                    unit = (gen_detail.get("unit") or "kWh").strip().lower()
                    val = float(gen_detail["value"])
                    kwh = val * 1000 if unit == "mwh" else val
                    if kwh > 0:
                        fuente = "medidor"
            except Exception as exc:
                logger.warning("project_detail fallo sol_id=%d: %s", sol_id, exc)

        return (p.id, p.nombre_comercial, sol_id, round(kwh, 1), fuente)

    result = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for pid, nombre, sol_id, kwh_real, fuente in executor.map(_fetch_kwh, matched):
            result.append({
                "proyecto_id": pid,
                "nombre":      nombre,
                "sol_id":      sol_id,
                "kwh_real":    kwh_real,
                "fuente":      fuente,
            })

    result.sort(key=lambda x: x["kwh_real"], reverse=True)
    data = {
        "fecha":    _hoy_col().isoformat(),
        "total":    round(sum(r["kwh_real"] for r in result), 1),
        "proyectos": result,
    }
    _cache_set(_GENHOY_KEY, CACHE_TTL_GENHOY, data)
    return data


@router.get("/resumen-dia")
def resumen_dia(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Resumen del día: top de generación por medidores y por inversores.

    - Medidor: `generation` de /config/project-detail/ por proyecto.
    - Inversor: `get_generation(ayer, hoy)` por proyecto, sumando las entradas de hoy.

    Las dos van en la misma pasada paralela. Ambas listas ordenadas desc.
    Cacheado en memoria (TTL corto).
    """
    _KEY = f"resumendia:{_hoy_col().isoformat()}"
    cached = _cache_get(_KEY)
    if cached:
        return cached

    client = _get_client()
    today_str = _hoy_col().isoformat()
    yesterday_str = (_hoy_col() - timedelta(days=1)).isoformat()

    proyectos_db = db.query(Proyecto).filter(Proyecto.estado == "en_operacion").all()
    matched = [(p, sid) for p in proyectos_db if (sid := _sv_id(p)) is not None]

    medidor: list[dict] = []

    # Las dos lecturas del proyecto en la misma pasada paralela. Antes el
    # medidor salia del lote de summary de Solenium (una sola llamada para toda
    # la flota); SolarView no tiene ese lote, asi que va por project-detail, una
    # por proyecto -- pero aprovechando el mismo worker que ya pedia la
    # generacion de inversores.
    def _lecturas(item: tuple) -> tuple:
        p, sol_id = item
        kwh_inv = 0.0
        try:
            gen = client.get_generation(sol_id, yesterday_str, today_str) or {}
            if "results" in gen:
                gen = gen["results"]
            kwh_inv = _sum_today_inverter_kwh(gen.get("generation_kwh") or {}, today_str,
                                              p.potencia_instalada_kwp)
        except Exception as exc:
            logger.warning("resumen-dia inversor sol_id=%s: %s", sol_id, exc)
        try:
            kwh_med = _meter_kwh_from_detail(client.get_project_detail(sol_id))
        except Exception as exc:
            logger.warning("resumen-dia medidor sol_id=%s: %s", sol_id, exc)
            kwh_med = None
        return (p.id, p.nombre_comercial, round(kwh_inv, 1), kwh_med)

    inversor: list[dict] = []
    if matched:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for pid, nombre, kwh_inv, kwh_med in ex.map(_lecturas, matched):
                if kwh_inv > 0:
                    inversor.append({"proyecto_id": pid, "nombre": nombre, "kwh": kwh_inv})
                if kwh_med and kwh_med > 0:
                    medidor.append({"proyecto_id": pid, "nombre": nombre, "kwh": round(kwh_med, 1)})

    medidor.sort(key=lambda x: x["kwh"], reverse=True)
    inversor.sort(key=lambda x: x["kwh"], reverse=True)

    data = {
        "fecha":    today_str,
        "medidor":  {"total": round(sum(x["kwh"] for x in medidor), 1),  "top": medidor},
        "inversor": {"total": round(sum(x["kwh"] for x in inversor), 1), "top": inversor},
    }
    _cache_set(_KEY, CACHE_TTL_GENHOY, data)
    return data


@router.get("/monitoring")
def fleet_monitoring(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Fleet monitoring: DB projects en operación, minigranja y con servicio de
    operación. Un proyecto sin project_id_solarview igual aparece, con status
    "sin_datos": sus medidores no dependen del proveedor y la tarjeta tiene que
    poder mostrarlos.
    Returns status (online/caido/degradado/sin_comunicacion/sin_datos) per project.
    Status determined by SolarView availability category:
      disconnect → sin_comunicacion
      critical   → caido
      low/medium → degradado
      high       → online
    """
    client = _get_client()

    proyectos = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
        Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
        Proyecto.srv_operacion == True,  # noqa: E712
    ).all()

    if not proyectos:
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "fleet": {"total": 0, "online": 0, "caido": 0, "degradado": 0,
                      "sin_comunicacion": 0, "sin_datos": 0, "total_capacity_kwp": 0},
            "projects": [],
        }

    # Caché de flota (evita llamadas Solenium por cada refresh)
    _FLEET_CACHE_KEY = f"fleet:{_hoy_col().isoformat()}"
    cached = _cache_get(_FLEET_CACHE_KEY)
    if cached:
        return cached

    # Una sola llamada para toda la flota: /kpis/availability/ devuelve el mismo
    # shape que el de Solenium a proposito, asi que el mapeo de status no cambia.
    #
    # Ya no se piden get_project_summary (SolarView no tiene ese lote) ni
    # get_projects: el catalogo del proveedor solo servia para emparejar por
    # nombre, y eso se elimino -- ver el docstring del modulo. Con eso tambien
    # desaparece la escritura en BD que hacia este GET como efecto secundario,
    # persistiendo un id adivinado.
    avail_map = client.get_availability() or {}

    today_str = _hoy_col().isoformat()
    today_rows = db.execute(
        text("SELECT proyecto_id, kwh_real FROM generacion_diaria "
             "WHERE fecha = :today AND kwh_real IS NOT NULL"),
        {"today": today_str},
    ).fetchall()
    today_gen_map = {int(r.proyecto_id): float(r.kwh_real) for r in today_rows}

    projects_result = []
    total_capacity = 0.0
    counts = {"online": 0, "caido": 0, "degradado": 0, "sin_comunicacion": 0}

    for p in proyectos:
        sol_id = _sv_id(p)
        # Un proyecto sin id reconciliado NO se excluye: la tarjeta igual tiene
        # que salir, porque sus medidores no dependen de ningun proveedor (se
        # resuelven por fronteras.proyecto_id). Antes se hacia `continue` y el
        # proyecto desaparecia entero de la vista.
        avail = avail_map.get(sol_id, {}) if sol_id else {}

        availability_cat = avail.get("category")
        capacity_kwp = float(p.potencia_instalada_kwp or 0)

        if availability_cat is None:
            # Ni id ni respuesta del proveedor: no es que la comunicacion este
            # caida, es que no sabemos. El frontend pinta gris cualquier status
            # que no reconozca.
            status = "sin_datos"
        elif availability_cat == "disconnect":
            status = "sin_comunicacion"
        elif availability_cat == "critical":
            status = "caido"
        elif availability_cat in ("low", "medium"):
            status = "degradado"
        else:
            status = "online"

        counts[status] = counts.get(status, 0) + 1
        total_capacity += capacity_kwp

        projects_result.append({
            "proyecto_id":           p.id,
            "nombre":                p.nombre_comercial,
            "sol_id":                sol_id,
            "status":                status,
            "availability_category": availability_cat,
            "availability_pct":      avail.get("availability"),
            "capacity_kwp":          round(capacity_kwp, 1),
            "energy_today_kwh":      today_gen_map.get(p.id),
        })

    _order = {"caido": 0, "sin_comunicacion": 1, "degradado": 2, "online": 3, "sin_datos": 4}
    projects_result.sort(key=lambda x: (_order.get(x["status"], 5), x["nombre"] or ""))

    result = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "fleet": {
            "total":              len(proyectos),
            "online":             counts["online"],
            "caido":              counts["caido"],
            "degradado":          counts["degradado"],
            "sin_comunicacion":   counts["sin_comunicacion"],
            "sin_datos":          counts.get("sin_datos", 0),
            "total_capacity_kwp": round(total_capacity, 1),
        },
        "projects": projects_result,
    }
    _cache_set(_FLEET_CACHE_KEY, CACHE_TTL_FLEET, result)
    return result


@router.get("/monitoring/{proyecto_id}")
def project_monitoring_detail(
    proyecto_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Detail monitoring for one project: inverter status + power curve today + 30d generation.
    Uses our internal proyecto_id, resolves to SolarView ID via project_id_solarview.
    """
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    # Sin id de SolarView NO se corta: los inversores quedan sin dato, pero el
    # medidor se resuelve por find_gaia_node_pair desde fronteras.proyecto_id,
    # un camino que no depende de ningun proveedor externo. Antes esto era un
    # 422 que dejaba la tarjeta entera vacia, incluida la mitad que si tenia
    # con que llenarse (2026-09-03).

    # Caché de detalle por proyecto (evita 21-30 llamadas externas por cada tarjeta)
    _detail_key = f"detail:{proyecto_id}:{_hoy_col().isoformat()}"
    cached = _cache_get(_detail_key)
    if cached:
        return cached

    sol_id = _sv_id(p)
    client = _get_client()

    today   = _hoy_col()
    start30 = (today - timedelta(days=29)).isoformat()

    # Resolve Gaia node IDs for this project (non-fatal if not found)
    gaia = _get_gaia()
    _db_fronteras = db.query(Frontera.proyecto_id, Frontera.codigo_frontera).filter(
        Frontera.tipo_frontera.in_([TipoFronteraEnum.generacion, TipoFronteraEnum.generacion_consumo]),
        Frontera.codigo_frontera.isnot(None),
    ).all()
    _db_proyecto_frt_map = build_db_proyecto_frt_map(list(_db_fronteras))
    node_principal, node_respaldo = find_gaia_node_pair(
        gaia=gaia,
        proyecto_id=p.id,
        db_proyecto_frt_map=_db_proyecto_frt_map,
    )

    hoy = today.isoformat()
    capacidad_mw = float(p.potencia_instalada_kwp or 0) / 1000 or None
    with ThreadPoolExecutor(max_workers=6) as ex:
        pow_f      = ex.submit(client.get_power, sol_id, hoy, hoy) if sol_id else None
        gen_f      = ex.submit(client.get_energy, sol_id, granularity="day",
                               date_from=start30, date_to=today.isoformat()) if sol_id else None
        gen_hoy_f  = ex.submit(client.get_generation, sol_id, hoy, hoy) if sol_id else None
        # Medidor: `ap` + `eae` por el mismo metodo que usa el pipeline del
        # ASIC, en vez del compuesto de 8 familias de variables (que para dos
        # nodos eran hasta 16 llamadas externas por tarjeta). Ver
        # services/mgs/medidor_tiempo_real.py.
        med_p_f    = ex.submit(snapshot_medidor, gaia, node_principal, hoy, capacidad_mw) if (gaia and node_principal) else None
        med_r_f    = ex.submit(snapshot_medidor, gaia, node_respaldo, hoy, capacidad_mw) if (gaia and node_respaldo) else None

    power_data = (pow_f.result() or {}) if pow_f else {}
    gen_raw    = (gen_f.result() or {}) if gen_f else {}
    gen_hoy    = (gen_hoy_f.result() or {}) if gen_hoy_f else {}
    # Total real de hoy calculado por Solenium (endpoint /generation/, más preciso
    # que integrar nosotros la curva de potencia de 5 min por trapecios).
    # No se usa `total_generation_kwh` de la respuesta: viene con los picos
    # espurios adentro. Se recalcula sumando solo las horas plausibles.
    _gen_hoy_res = gen_hoy.get("results", gen_hoy) if isinstance(gen_hoy, dict) else {}
    _gen_map = (_gen_hoy_res or {}).get("generation_kwh") or {}
    generation_today_kwh = _sum_today_inverter_kwh(_gen_map, hoy, p.potencia_instalada_kwp) or None

    # Hasta que hora cubre ese total, para poder decirlo igual que el medidor:
    # son horas sumadas, no una lectura del ultimo instante. Solo se miran las
    # horas que sobrevivieron el filtro de plausibilidad.
    _limite = _limite_hora_kwh(p.potencia_instalada_kwp)
    _horas_ok = [
        k for k, v in _gen_map.items()
        if str(k).startswith(hoy) and _es_hora_plausible(v, _limite)
    ]
    generation_today_hasta = max(_horas_ok)[11:16] if _horas_ok else None

    med_p = med_p_f.result() if med_p_f else None
    med_r = med_r_f.result() if med_r_f else None

    # La eleccion vive SOLO aca. Antes el mismo criterio ("mayor energia")
    # estaba escrito tambien en SolarLiveView.vue, y podian desincronizarse en
    # silencio: la grafica mostrando un medidor y el resto de la tarjeta otro.
    medidor, medidor_tipo = elegir_medidor(med_p, med_r)
    best_node = medidor["node_id"] if medidor else (node_principal or node_respaldo)

    # ── Fetch per-inverter detail in parallel (strings + AC metrics) ─────────
    # El array `inverters` del detalle no lo consume nadie: la vista movil que
    # muestra inversores (InvertersSheet.vue) los saca de
    # /monitoring/{id}/inverters-power, que es otro endpoint. Y `strings` /
    # `ac_metrics` tampoco se leen en ninguna parte.
    #
    # Por eso se dejo de pedir get_project_inverters y, sobre todo, el detalle
    # POR INVERSOR: eran hasta 11 llamadas externas mas por tarjeta (San Pedro
    # tiene 11 inversores) para llenar campos que nadie mira. Si algun dia hace
    # falta el detalle de strings, en SolarView vive en /measurements/dc/, no en
    # inverter-detail.
    processed_inverters: list[dict] = []

    # ── Power curve today: sum all inverters per timestamp ────────────────
    power_total: dict[str, float] = {}
    raw_power = {}
    if isinstance(power_data, dict):
        raw_power = (power_data.get("power")
                     or power_data.get("results", {}).get("power")
                     or {})
    # Con total_power=1 (ver SolarViewClient.get_power) la API ya entrega la
    # potencia SUMADA entre todos los inversores, o sea un {ts: kw} plano. La
    # API vieja de Solenium devolvia {inversor: {ts: kw}} y habia que sumar
    # aca; ese loop anidado descartaba en silencio la respuesta nueva, porque
    # los valores son numeros y no dicts.
    for ts, val in raw_power.items():
        try:
            power_total[ts] = float(val or 0)
        except (TypeError, ValueError):
            continue

    power_curve = [
        {"time": ts, "kw": round(v, 2)}
        for ts, v in sorted(power_total.items())
    ]

    # ── 30d daily generation (desde get_energy granularity=day) ─────────────
    gen_results = gen_raw.get("results") if isinstance(gen_raw, dict) else None
    gen_points = gen_results.get("points") if isinstance(gen_results, dict) else None
    gen_unit = (gen_results.get("unit") or "kWh").strip().lower() if isinstance(gen_results, dict) else "kwh"
    gen_factor = 1000.0 if gen_unit == "mwh" else 1.0

    daily: dict[str, float] = {}
    if isinstance(gen_points, list):
        for item in gen_points:
            if not isinstance(item, dict):
                continue
            d = item.get("time") or item.get("date") or item.get("day")
            val = item.get("kwh")
            if val is None:
                val = item.get("value") or item.get("energy")
            if d and val is not None:
                d = str(d)[:10]
                daily[d] = daily.get(d, 0.0) + float(val) * gen_factor
    generation_30d = [
        {"date": d, "kwh": round(v, 1)}
        for d, v in sorted(daily.items())
    ]

    has_strings = any(inv.get("strings") for inv in processed_inverters)

    result = {
        "proyecto_id":            p.id,
        "nombre":                 p.nombre_comercial,
        "sol_id":                 sol_id,
        "gaia_node_id":           best_node,
        "gaia_node_principal":    node_principal,
        "gaia_node_respaldo":     node_respaldo,
        "capacity_kwp":           float(p.potencia_instalada_kwp or 0),
        "inverters":              processed_inverters,
        "power_curve":            power_curve,
        "generation_today_kwh":   round(generation_today_kwh, 1) if generation_today_kwh is not None else None,
        "generation_today_hasta": generation_today_hasta,
        "generation_30d":         generation_30d,
        "total_30d_kwh":          round(sum(d["kwh"] for d in generation_30d), 1),
        "has_strings":            has_strings,
        # Medidor ya elegido y resuelto -- el frontend lo dibuja, no lo decide.
        "medidor":                medidor,
        "medidor_tipo":           medidor_tipo,
        "medidor_principal":      med_p,
        "medidor_respaldo":       med_r,
    }
    _cache_set(_detail_key, CACHE_TTL_DETAIL, result)
    return result


@router.get("/monitoring/{proyecto_id}/inverters-power")
def project_inverters_power(
    proyecto_id: int,
    date_from: str = Query(None, description="YYYY-MM-DD (default: hoy)"),
    date_to: str = Query(None, description="YYYY-MM-DD (default: hoy)"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Potencia por inversor (serie temporal) de un proyecto, en un rango de fechas.

    Solenium devuelve `power` como dict llaveado por dev_name del inversor. Aquí lo
    normalizamos a una lista de series — una por inversor — que el front usa tanto
    para la gráfica comparativa (todas las líneas) como para la individual (al
    expandir un inversor; filtra por dev_name).

    Sin fechas → hoy (resolución 5 min). En rangos de varios días se agrupa por hora.
    """
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    if not p.project_id_solarview:
        raise HTTPException(422, "Proyecto sin ID SolarView")

    sol_id = _sv_id(p)
    today = date.today().isoformat()
    df = date_from or today
    dt = date_to or today

    client = _get_client()
    # total_power=0 -> series POR INVERSOR ({nombre: {ts: kw}}), que es lo que
    # este endpoint arma. Con el default (1) la API entrega la suma del proyecto
    # en un dict plano y el loop de abajo lo descartaba entero, devolviendo cero
    # inversores sin ningun error.
    raw = client.get_power(sol_id, df, dt, total_power=0) or {}
    power = raw.get("power") or (raw.get("results") or {}).get("power") or {}

    multiday = df != dt
    inverters: list[dict] = []
    for dev_name, series in power.items():
        if not isinstance(series, dict):
            continue
        pts = sorted(series.items())
        if multiday:
            # Agrupar por hora: promedio de potencia por franja "YYYY-MM-DD HH"
            buckets: dict[str, list[float]] = {}
            for ts, v in pts:
                buckets.setdefault(str(ts)[:13], []).append(float(v or 0))
            points = [{"time": f"{k}:00", "kw": round(sum(vs) / len(vs), 2)}
                      for k, vs in sorted(buckets.items())]
        else:
            points = [{"time": str(ts), "kw": round(float(v or 0), 2)} for ts, v in pts]
        peak = max((pt["kw"] for pt in points), default=0.0)
        inverters.append({"dev_name": dev_name, "points": points, "peak_kw": round(peak, 2)})

    inverters.sort(key=lambda x: x["dev_name"])
    return {
        "proyecto_id":  p.id,
        "sol_id":       sol_id,
        "date_from":    df,
        "date_to":      dt,
        "granularidad": "hour" if multiday else "5min",
        "inverters":    inverters,
    }


