"""Cliente de la API Unergy tal como lo usa Cumplimiento.

Copiado SIN CAMBIOS de `app/api/v1/cumplimiento.py`: son lecturas de generación
contra una API externa, no tocan la base y no hay nada que traducir al ORM. La
única diferencia es de dónde sale `settings` (ver `apps/comun/config.py`).

`apps/energia/services/unergy_api.py` habla con la misma API con otro contrato
(deltas horarios para las gráficas). No se unificaron: éste devuelve MWh
mensuales agregados y aquél kWh por intervalo, y fundirlos obligaría a reverificar
las dos formas contra la API.
"""

from __future__ import annotations

import calendar
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from apps.comun.config import settings

logger = logging.getLogger("operaciones.cumplimiento")

_COL_TZ = timezone(timedelta(hours=-5))

def _unergy_token() -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{settings.UNERGY_API_URL}/api/accounts/{settings.UNERGY_ACCOUNT_ID}/",
            json={"login": settings.UNERGY_LOGIN, "password": settings.UNERGY_PASSWORD},
            headers={"User-Agent": "PostmanRuntime/7.50.0"},
        )
        resp.raise_for_status()
        return resp.json()["access"]

def _monthly_mwh_from_records(records: list) -> dict:
    """Calcula los MWh del mes a partir de registros de un contador acumulado.

    Reglas (función pura, testeable):
    - Ignora lecturas con ``generacion`` None: una lectura faltante NO es 0; antes
      ``or 0`` la forzaba a 0 y podía hacer que el mes reportara 0 MWh en vez de
      "sin dato" cuando la lectura de borde venía nula.
    - Suma los deltas positivos entre lecturas consecutivas. Esto es robusto ante
      reinicios de contador (un paso negativo aporta 0 en vez de corromper el
      total) y es EXACTAMENTE igual a (último − primero) cuando el contador es
      monótono creciente, que es el caso normal. Así el cálculo no cambia para los
      meses sanos y solo se corrige el caso anómalo (reinicio / lectura nula).

    Devuelve ``mwh`` (float redondeado a 3) o None si no hay lecturas válidas, y
    el datetime tz-aware (Colombia) de la última lectura válida en ``last_dt``.
    """
    rows = []
    for r in sorted(records, key=lambda r: r.get("time_stamp", "")):
        g = r.get("generacion")
        if g is None:
            continue
        rows.append((r.get("time_stamp", ""), float(g)))

    if not rows:
        return {"mwh": None, "n_used": 0, "last_dt": None}

    total_kwh = 0.0
    for (_, prev), (_, cur) in zip(rows, rows[1:]):
        if cur > prev:
            total_kwh += cur - prev

    last_dt = None
    try:
        last_aware = datetime.fromisoformat(rows[-1][0].replace("Z", "+00:00"))
        # Normalizar a hora Colombia antes de leer el día: si la API entrega el
        # timestamp en UTC ("...Z"), el .day crudo podía rodar al mes siguiente
        # en lecturas cercanas a medianoche (fin de mes).
        last_dt = last_aware.astimezone(_COL_TZ)
    except Exception:
        last_dt = None

    return {"mwh": round(total_kwh / 1000, 3), "n_used": len(rows), "last_dt": last_dt}

def _fetch_month(token: str, sub_project: str, year: int, month: int) -> dict:
    """
    Consulta la generación acumulada de un mes para un sub_project.
    Devuelve MWh del mes = (último acumulado – primero) / 1000.
    Colombia = UTC-5: agrega 5h para obtener el timestamp UTC correcto.
    """
    tz_offset = timedelta(hours=5)
    last_day = calendar.monthrange(year, month)[1]
    start_utc = datetime(year, month, 1, 0, 0, 0) + tz_offset
    end_utc = datetime(year, month, last_day, 23, 59, 59) + tz_offset

    try:
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/",
                params={
                    "time_stamp__gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                    "limit": "10000",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "PostmanRuntime/7.50.0",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.warning("API error sub_project=%s %d-%02d: %s", sub_project, year, month, exc)
        return {"mwh": None, "n_records": 0, "ultimo_dia": None}

    if not records:
        return {"mwh": None, "n_records": 0, "ultimo_dia": None}

    calc = _monthly_mwh_from_records(records)
    ultimo_dia = calc["last_dt"].day if calc["last_dt"] is not None else None

    return {
        "mwh": calc["mwh"],
        "n_records": len(records),
        "ultimo_dia": ultimo_dia,
    }

def _fetch_recent_avg(token: str, sub_project: str, n_days: int = 15) -> dict:
    """
    Promedio diario de generación en los últimos n_days días con datos reales.
    Consulta los 60 días previos a hoy para encontrar días con producción > 0.
    Usa para proyectar meses futuros donde no hay datos reales.
    """
    now_col = datetime.now(timezone.utc) - timedelta(hours=5)
    start_col = now_col - timedelta(days=60)
    tz_offset = timedelta(hours=5)
    start_utc = start_col + tz_offset
    end_utc = now_col + tz_offset

    try:
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/",
                params={
                    "time_stamp__gte": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                    "limit": "10000",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "PostmanRuntime/7.50.0",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.warning("API error recent_avg sub_project=%s: %s", sub_project, exc)
        return {"avg_daily_mwh": None, "n_days_used": 0, "last_data_date": None}

    if not records:
        return {"avg_daily_mwh": None, "n_days_used": 0, "last_data_date": None}

    by_day: dict = defaultdict(list)
    for r in records:
        ts_str = r.get("time_stamp", "")
        gen_val = r.get("generacion")
        if not ts_str or gen_val is None:
            continue
        try:
            dt_aware = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            dt_col = dt_aware.astimezone(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
            by_day[dt_col.date()].append(float(gen_val))
        except Exception:
            continue

    daily_gen = []
    for day, vals in by_day.items():
        delta_mwh = (max(vals) - min(vals)) / 1000
        if delta_mwh > 0:
            daily_gen.append((day, delta_mwh))

    if not daily_gen:
        return {"avg_daily_mwh": None, "n_days_used": 0, "last_data_date": None}

    daily_gen.sort(key=lambda x: x[0])
    recent = daily_gen[-n_days:]
    avg = round(sum(v for _, v in recent) / len(recent), 3)
    return {
        "avg_daily_mwh": avg,
        "n_days_used": len(recent),
        "last_data_date": recent[-1][0].isoformat(),
    }

def _sumar_deltas_en_rango(records: list, d_from_utc: datetime, d_to_utc: datetime) -> Optional[float]:
    """Suma la generación REAL entre lecturas consecutivas cuyo timestamp cae en
    [d_from_utc, d_to_utc] (ambos naive-UTC, igual que `time_stamp` de la API).

    Usa la última lectura ANTERIOR al rango como base del primer delta, para no
    perder la generación de las primeras horas del día de inicio (si no hubiera
    "antes", ese primer intervalo no tendría con qué compararse). Ignora deltas
    negativos (reinicio de contador), mismo criterio que `_monthly_mwh_from_records`.

    Es el mismo método que usa la vista "Generación solar" al filtrar por rango
    (`_compute_deltas` en monitoreo.py) — sumar días reales, no repartir el
    total del mes por fracción de días.
    """
    rows = []
    for r in records:
        ts_raw = r.get("time_stamp", "")
        gen = r.get("generacion")
        if not ts_raw or gen is None:
            continue
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            continue
        rows.append((ts, float(gen)))
    rows.sort(key=lambda x: x[0])

    before = [x for x in rows if x[0] < d_from_utc]
    period = [x for x in rows if d_from_utc <= x[0] <= d_to_utc]
    if not period:
        return None

    working = ([before[-1]] if before else []) + period
    total_kwh = 0.0
    for (_, prev), (_, cur) in zip(working, working[1:]):
        if cur > prev:
            total_kwh += cur - prev
    return round(total_kwh / 1000, 3)

def _fetch_range(token: str, sub_project: str, start: date, end: date) -> dict:
    """
    Generación REAL de un sub_project entre `start` y `end` (ambos inclusive),
    sumando los deltas de cada lectura — NO reparte el total del mes por
    fracción de días. Se usa cuando un registro GESCON solo estuvo vigente
    PARTE del mes (relevo, arranque o terminación a mitad de mes): el total
    mensual prorrateado por días no coincide con la generación real de esos
    días específicos porque la generación diaria no es pareja (clima, etc.).

    Colchón de 2 días antes de `start` para poder calcular el delta del primer
    punto dentro del rango (sin una lectura "antes" no hay con qué comparar el
    primer dato del día de inicio).
    """
    tz_offset = timedelta(hours=5)  # Colombia = UTC-5
    d_from = datetime(start.year, start.month, start.day, 0, 0, 0)
    d_to = datetime(end.year, end.month, end.day, 23, 59, 59)
    fetch_from_utc = (d_from - timedelta(days=2)) + tz_offset
    d_from_utc = d_from + tz_offset
    d_to_utc = d_to + tz_offset

    try:
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            resp = client.get(
                f"{settings.UNERGY_API_URL}/api/admin/operations/project_generation/",
                params={
                    "time_stamp__gte": fetch_from_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "time_stamp__lte": d_to_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sub_project": sub_project,
                    "limit": "10000",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "PostmanRuntime/7.50.0",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("results", [])
    except Exception as exc:
        logger.warning("API error rango sub_project=%s %s..%s: %s", sub_project, start, end, exc)
        return {"mwh": None, "n_records": 0}

    if not records:
        return {"mwh": None, "n_records": 0}

    mwh = _sumar_deltas_en_rango(records, d_from_utc, d_to_utc)
    return {"mwh": mwh, "n_records": len(records)}
