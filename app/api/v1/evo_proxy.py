"""EVO API proxy — forwards requests to EVO (DailySpot + Clima) via Tailscale."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from app.api.v1.auth import get_current_user
from app.core.config import settings

router = APIRouter(prefix="/evo", tags=["EVO Proxy"])

_TIMEOUT = httpx.Timeout(10.0, read=30.0)


def _evo_get(path: str, params: dict | None = None) -> dict:
    if not settings.EVO_API_URL:
        raise HTTPException(503, "EVO_API_URL not configured")
    url = f"{settings.EVO_API_URL.rstrip('/')}/{path.lstrip('/')}"
    headers = {}
    if settings.EVO_API_TOKEN:
        headers["X-EVO-Token"] = settings.EVO_API_TOKEN
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


@router.get("/dailyspot/latest")
def evo_dailyspot_latest(_=Depends(get_current_user)):
    return _evo_get("/dailyspot/latest")


@router.get("/dailyspot/text")
def evo_dailyspot_text(_=Depends(get_current_user)):
    return _evo_get("/dailyspot/text")


@router.get("/clima/forecast")
def evo_clima_forecast(_=Depends(get_current_user)):
    return _evo_get("/clima/forecast")


@router.get("/clima/trading")
def evo_clima_trading(tariff: float | None = None, _=Depends(get_current_user)):
    params = {"tariff": tariff} if tariff is not None else None
    return _evo_get("/clima/trading", params=params)


@router.get("/health")
def evo_health(_=Depends(get_current_user)):
    return _evo_get("/health")
