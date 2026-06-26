"""EVO API proxy — forwards requests to EVO (DailySpot + Clima) via Tailscale."""
import json
import logging
import threading

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.v1.auth import get_current_user, _require_admin
from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger("evo_proxy")
router = APIRouter(prefix="/evo", tags=["EVO Proxy"])

_TIMEOUT = httpx.Timeout(10.0, read=30.0)


def _evo_get(path: str, params: dict | None = None) -> dict:
    if not settings.EVO_API_URL:
        raise HTTPException(503, "EVO_API_URL not configured")
    url = f"{settings.EVO_API_URL.rstrip('/')}/{path.lstrip('/')}"
    headers = {}
    if settings.EVO_API_TOKEN.get_secret_value():
        headers["X-EVO-Token"] = settings.EVO_API_TOKEN.get_secret_value()
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(503, "EVO unreachable")
    except httpx.TimeoutException:
        raise HTTPException(504, "EVO timeout")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)


def _persist_dailyspot(data: dict):
    """Save DailySpot data to precios_bolsa tables (fire-and-forget)."""
    try:
        fecha = data.get("date")
        if not fecha:
            return
        summary = data.get("summary", {})
        prices = data.get("prices", {})
        generation = data.get("generation", {})
        marginals = data.get("marginal_plants", {})

        db = SessionLocal()
        try:
            db.execute(text("""
                INSERT INTO precios_bolsa_diario
                    (fecha, precio_promedio, precio_min, precio_max, precio_escasez,
                     demanda_gwh, hidro_pct, termica_pct, renovable_pct, menor_pct,
                     hora_pico, spread, source_data)
                VALUES (:fecha, :avg, :min, :max, :escasez,
                        :demanda, :hidro, :termica, :renovable, :menor,
                        :pico, :spread, :source)
                ON CONFLICT (fecha) DO UPDATE SET
                    precio_promedio = EXCLUDED.precio_promedio,
                    precio_min = EXCLUDED.precio_min,
                    precio_max = EXCLUDED.precio_max,
                    precio_escasez = EXCLUDED.precio_escasez,
                    demanda_gwh = EXCLUDED.demanda_gwh,
                    hidro_pct = EXCLUDED.hidro_pct,
                    termica_pct = EXCLUDED.termica_pct,
                    renovable_pct = EXCLUDED.renovable_pct,
                    menor_pct = EXCLUDED.menor_pct,
                    hora_pico = EXCLUDED.hora_pico,
                    spread = EXCLUDED.spread,
                    source_data = EXCLUDED.source_data
            """), {
                "fecha": fecha,
                "avg": summary.get("price_avg"),
                "min": summary.get("price_min"),
                "max": summary.get("price_max"),
                "escasez": data.get("scarcity_price"),
                "demanda": summary.get("total_gwh"),
                "hidro": summary.get("hydro_pct"),
                "termica": summary.get("thermal_pct"),
                "renovable": summary.get("renewable_pct"),
                "menor": summary.get("minor_pct"),
                "pico": summary.get("peak_hour"),
                "spread": summary.get("spread"),
                "source": json.dumps({"fetched_at": data.get("fetched_at")}),
            })

            for hour_str, price in prices.items():
                hour = int(hour_str)
                gen = generation.get(hour_str, {})
                db.execute(text("""
                    INSERT INTO precios_bolsa_horario
                        (fecha, hora, precio_cop_kwh, gen_hidro, gen_termica,
                         gen_renovable, gen_menor, planta_marginal)
                    VALUES (:fecha, :hora, :precio, :hidro, :termica,
                            :renovable, :menor, :marginal)
                    ON CONFLICT (fecha, hora) DO UPDATE SET
                        precio_cop_kwh = EXCLUDED.precio_cop_kwh,
                        gen_hidro = EXCLUDED.gen_hidro,
                        gen_termica = EXCLUDED.gen_termica,
                        gen_renovable = EXCLUDED.gen_renovable,
                        gen_menor = EXCLUDED.gen_menor,
                        planta_marginal = EXCLUDED.planta_marginal
                """), {
                    "fecha": fecha, "hora": hour, "precio": price,
                    "hidro": gen.get("Hidraulica"),
                    "termica": gen.get("Termica"),
                    "renovable": gen.get("Renovables"),
                    "menor": gen.get("Menores"),
                    "marginal": marginals.get(hour_str),
                })

            db.commit()
            logger.info("Persisted DailySpot for %s (%d hours)", fecha, len(prices))
        except Exception:
            db.rollback()
            logger.exception("Failed to persist DailySpot")
        finally:
            db.close()
    except Exception:
        logger.exception("DailySpot persist error")


def _persist_forecast(data: dict):
    """Save clima forecast to clima_forecasts table."""
    try:
        if not data.get("models_available"):
            return
        db = SessionLocal()
        try:
            db.execute(text("""
                INSERT INTO clima_forecasts (forecast_date, forecast_json, model_version)
                VALUES (CURRENT_DATE, :data, :version)
                ON CONFLICT DO NOTHING
            """), {
                "data": json.dumps(data, default=str),
                "version": data.get("source", "unknown"),
            })
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist forecast")
        finally:
            db.close()
    except Exception:
        logger.exception("Forecast persist error")


@router.get("/dailyspot/latest")
def evo_dailyspot_latest(_=Depends(get_current_user)):
    data = _evo_get("/dailyspot/latest")
    threading.Thread(target=_persist_dailyspot, args=(data,), daemon=True).start()
    return data


@router.get("/dailyspot/text")
def evo_dailyspot_text(_=Depends(get_current_user)):
    return _evo_get("/dailyspot/text")


@router.get("/dailyspot/history")
def evo_dailyspot_history(
    days: int = Query(30, ge=1, le=365),
    _=Depends(get_current_user),
):
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT fecha, precio_promedio, precio_min, precio_max,
                   precio_escasez, demanda_gwh, hidro_pct, spread, hora_pico
            FROM precios_bolsa_diario
            ORDER BY fecha DESC LIMIT :days
        """), {"days": days}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/dailyspot/hourly/{fecha}")
def evo_dailyspot_hourly(fecha: str, _=Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT hora, precio_cop_kwh, gen_hidro, gen_termica,
                   gen_renovable, gen_menor, planta_marginal
            FROM precios_bolsa_horario
            WHERE fecha = :fecha ORDER BY hora
        """), {"fecha": fecha}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/clima/forecast")
def evo_clima_forecast(_=Depends(get_current_user)):
    data = _evo_get("/clima/forecast")
    threading.Thread(target=_persist_forecast, args=(data,), daemon=True).start()
    return data


@router.get("/clima/trading")
def evo_clima_trading(tariff: float | None = None, _=Depends(get_current_user)):
    params = {"tariff": tariff} if tariff is not None else None
    return _evo_get("/clima/trading", params=params)


@router.get("/clima/history")
def evo_clima_history(
    limit: int = Query(10, ge=1, le=100),
    _=Depends(get_current_user),
):
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, forecast_date, model_version, created_at
            FROM clima_forecasts
            ORDER BY forecast_date DESC LIMIT :limit
        """), {"limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/clima/forecast/{forecast_id}")
def evo_clima_forecast_detail(forecast_id: int, _=Depends(get_current_user)):
    """Retrieve full forecast JSON by ID."""
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT id, forecast_date, forecast_json, model_version, created_at
            FROM clima_forecasts
            WHERE id = :fid
        """), {"fid": forecast_id}).first()
        if not row:
            raise HTTPException(404, "Forecast not found")
        return dict(row._mapping)
    finally:
        db.close()


@router.get("/precios/historico")
def evo_precios_historico(
    desde: str = Query(None, description="Start date YYYY-MM-DD"),
    hasta: str = Query(None, description="End date YYYY-MM-DD"),
    limit: int = Query(365, ge=1, le=3650),
    _=Depends(get_current_user),
):
    """Historical spot prices with optional date range filter."""
    db = SessionLocal()
    try:
        params: dict = {"limit": limit}
        where_clauses = []
        if desde:
            where_clauses.append("fecha >= :desde")
            params["desde"] = desde
        if hasta:
            where_clauses.append("fecha <= :hasta")
            params["hasta"] = hasta
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = db.execute(text(f"""
            SELECT fecha, precio_promedio, precio_min, precio_max,
                   precio_escasez, demanda_gwh, hidro_pct, termica_pct,
                   renovable_pct, menor_pct, hora_pico, spread
            FROM precios_bolsa_diario
            {where_sql}
            ORDER BY fecha DESC LIMIT :limit
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/clima/oni")
def evo_clima_oni(
    years: int = Query(10, ge=1, le=80),
    _=Depends(get_current_user),
):
    """Historical ONI index with ENSO phases."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT year, month, oni_value, soi_value, pdo_value, mjo_amplitude, enso_phase
            FROM clima_oni_monthly
            ORDER BY year DESC, month DESC
            LIMIT :limit
        """), {"limit": years * 12}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/clima/prices")
def evo_clima_prices(
    years: int = Query(26, ge=1, le=30),
    _=Depends(get_current_user),
):
    """Historical energy prices with ENSO phase."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT p.year, p.month, p.price_cop_kwh, p.enso_phase,
                   o.oni_value
            FROM clima_price_monthly p
            LEFT JOIN clima_oni_monthly o ON p.year = o.year AND p.month = o.month
            ORDER BY p.year DESC, p.month DESC
            LIMIT :limit
        """), {"limit": years * 12}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/clima/precip")
def evo_clima_precip(
    region: str = Query("Andina"),
    years: int = Query(10, ge=1, le=40),
    _=Depends(get_current_user),
):
    """Historical precipitation for a region."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT year, month, precip_mm, anomaly_pct, climatology_mm
            FROM clima_precip_monthly
            WHERE region = :region
            ORDER BY year DESC, month DESC
            LIMIT :limit
        """), {"region": region, "limit": years * 12}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/health")
def evo_health(_=Depends(get_current_user)):
    return _evo_get("/health")


@router.post("/clima/bulk-load")
def evo_clima_bulk_load(payload: dict, _=Depends(_require_admin)):
    """Admin endpoint: bulk load climate indices and price history."""
    db = SessionLocal()
    counts = {"oni": 0, "precip": 0, "prices": 0}
    try:
        for row in payload.get("oni", []):
            db.execute(text("""
                INSERT INTO clima_oni_monthly (year, month, oni_value, soi_value, pdo_value, mjo_amplitude, enso_phase)
                VALUES (:year, :month, :oni, :soi, :pdo, :mjo, :phase)
                ON CONFLICT (year, month) DO UPDATE SET
                    oni_value=EXCLUDED.oni_value, soi_value=EXCLUDED.soi_value,
                    pdo_value=EXCLUDED.pdo_value, mjo_amplitude=EXCLUDED.mjo_amplitude,
                    enso_phase=EXCLUDED.enso_phase
            """), row)
            counts["oni"] += 1

        for row in payload.get("precip", []):
            db.execute(text("""
                INSERT INTO clima_precip_monthly (year, month, region, precip_mm, anomaly_pct, climatology_mm)
                VALUES (:year, :month, :region, :precip_mm, :anomaly_pct, :climatology_mm)
                ON CONFLICT (year, month, region) DO UPDATE SET
                    precip_mm=EXCLUDED.precip_mm, anomaly_pct=EXCLUDED.anomaly_pct,
                    climatology_mm=EXCLUDED.climatology_mm
            """), row)
            counts["precip"] += 1

        for row in payload.get("prices", []):
            db.execute(text("""
                INSERT INTO clima_price_monthly (year, month, price_cop_kwh, enso_phase, precip_andina_mm)
                VALUES (:year, :month, :price_cop_kwh, :enso_phase, :precip_andina_mm)
                ON CONFLICT (year, month) DO UPDATE SET
                    price_cop_kwh=EXCLUDED.price_cop_kwh, enso_phase=EXCLUDED.enso_phase,
                    precip_andina_mm=EXCLUDED.precip_andina_mm
            """), row)
            counts["prices"] += 1

        db.commit()
        return {"status": "ok", "loaded": counts}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Bulk load failed: {e}")
    finally:
        db.close()
