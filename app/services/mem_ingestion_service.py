"""Servicio de ingesta del MEM/XM (precio de bolsa + asignaciones) vía REST.

NO confundir con ``app/services/xm/`` (descarga masiva por FTP de archivos SIC).
Esto es un cliente HTTP liviano a la API de datos del mercado, usado por la
automatización de liquidación para traer el precio de bolsa del período de un
informe y correlacionarlo con la generación.

Diseño para pruebas: las funciones públicas aceptan un ``request_fn`` inyectable
(mismo patrón que ``app/services/xm/downloader.py``). En producción es un cliente
``httpx`` con reintentos y backoff; en tests se pasa un stub que devuelve el
payload crudo sin tocar la red.

El parseo del payload crudo a los schemas de ``app/schemas/mem.py`` vive en
funciones puras (``_parse_precios`` / ``_parse_asignaciones``) fáciles de testear.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Callable, Optional

import httpx

from app.core.config import settings
from app.schemas.mem import AsignacionMEM, PrecioBolsaDia

logger = logging.getLogger(__name__)

# Endpoints/metricas del proveedor. Se dejan como constantes para poder ajustarlas
# sin tocar la lógica; el cliente arma POST {base}/{endpoint} con el rango de fechas.
ENDPOINT_PRECIO_BOLSA = "PrecBolsNaci"      # precio de bolsa nacional
ENDPOINT_ASIGNACIONES = "AsignacionEnergia"


class MEMIngestionError(RuntimeError):
    """Falla irrecuperable hablando con la API del MEM (tras agotar reintentos)."""


# Tipo del inyectable: (endpoint, body) -> payload dict ya deserializado de JSON.
RequestFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def _default_request_fn(
    *,
    base_url: str,
    api_key: str,
    timeout: float,
    max_retries: int,
    client: Optional[httpx.Client] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> RequestFn:
    """Construye el ``request_fn`` real: POST con reintentos y backoff exponencial.

    Reintenta ante errores de red y respuestas 5xx / 429. NO reintenta ante 4xx
    (salvo 429), porque un 400/401/404 no se arregla repitiendo.
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    def _do(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/{endpoint}"
        owns_client = client is None
        cli = client or httpx.Client(timeout=timeout)
        try:
            ultimo_error: Exception | None = None
            for intento in range(1, max_retries + 1):
                try:
                    resp = cli.post(url, json=body, headers=headers)
                    if resp.status_code >= 500 or resp.status_code == 429:
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}", request=resp.request, response=resp
                        )
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    ultimo_error = exc
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    # 4xx (excepto 429) no se reintenta.
                    if status is not None and 400 <= status < 500 and status != 429:
                        logger.warning("MEM %s devolvió %s; no se reintenta", endpoint, status)
                        raise MEMIngestionError(
                            f"MEM {endpoint} respondió {status}"
                        ) from exc
                    if intento < max_retries:
                        espera = min(2 ** (intento - 1), 30)
                        logger.warning(
                            "MEM %s falló (intento %s/%s): %s — reintentando en %ss",
                            endpoint, intento, max_retries, exc, espera,
                        )
                        sleep_fn(espera)
                    else:
                        logger.error(
                            "MEM %s falló tras %s intentos: %s", endpoint, max_retries, exc
                        )
            raise MEMIngestionError(
                f"MEM {endpoint} falló tras {max_retries} intentos: {ultimo_error}"
            ) from ultimo_error
        finally:
            if owns_client:
                cli.close()

    return _do


def _iter_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae la lista de registros de la respuesta, tolerante a la forma exacta.

    XM suele envolver los datos en ``Items``; se aceptan variantes comunes.
    """
    if payload is None:
        return []
    for clave in ("Items", "items", "data", "Data", "result", "Result"):
        val = payload.get(clave)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    # Si el payload YA es una lista envuelta o un solo registro.
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _get_ci(d: dict[str, Any], *claves: str) -> Any:
    """Lookup case-insensitive de la primera clave presente."""
    lower = {k.lower(): v for k, v in d.items()}
    for c in claves:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_precios(payload: dict[str, Any]) -> list[PrecioBolsaDia]:
    """Normaliza el payload de precio de bolsa a COP/kWh por fecha.

    XM publica el precio en COP/kWh en el reporte de precio de bolsa nacional;
    si viniera en COP/MWh (valores ~10^5) se detecta y convierte, para que el
    orquestador siempre multiplique por kWh sin ambigüedad.
    """
    out: list[PrecioBolsaDia] = []
    for item in _iter_items(payload):
        f = _get_ci(item, "Date", "fecha", "FechaHora", "Fecha")
        precio = _to_float(_get_ci(item, "Value", "valor", "precio", "PrecBolsNaci", "Price"))
        if f is None or precio is None:
            continue
        fecha = _coerce_date(f)
        if fecha is None:
            continue
        # Heurística de unidad: el precio de bolsa en COP/kWh está típicamente en
        # cientos; en COP/MWh en cientos de miles. Si es claramente MWh, se divide.
        if precio > 5000:
            precio = precio / 1000.0
        try:
            out.append(PrecioBolsaDia(fecha=fecha, precio_cop_kwh=precio))
        except ValueError as exc:
            logger.warning("Precio de bolsa inválido para %s: %s", fecha, exc)
    return out


def _parse_asignaciones(payload: dict[str, Any]) -> list[AsignacionMEM]:
    out: list[AsignacionMEM] = []
    for item in _iter_items(payload):
        f = _get_ci(item, "Date", "fecha", "Fecha")
        agente = _get_ci(item, "Agente", "agente", "Agent", "Code", "codigo")
        energia = _to_float(_get_ci(item, "Value", "valor", "energia", "energia_kwh"))
        fecha = _coerce_date(f) if f is not None else None
        if fecha is None or energia is None:
            continue
        out.append(
            AsignacionMEM(
                fecha=fecha,
                agente=str(agente) if agente is not None else "",
                energia_kwh=energia,
                codigo_frontera=_get_ci(item, "Frontera", "frontera", "codigo_frontera"),
            )
        )
    return out


def _coerce_date(v: Any) -> Optional[date]:
    if isinstance(v, date):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()[:10]  # YYYY-MM-DD (recorta 'T...' si viene datetime)
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _build_request_fn() -> RequestFn:
    return _default_request_fn(
        base_url=settings.XM_API_URL,
        api_key=settings.XM_API_KEY.get_secret_value() if settings.XM_API_KEY else "",
        timeout=settings.XM_API_TIMEOUT_SECONDS,
        max_retries=settings.XM_API_MAX_RETRIES,
    )


def get_precios_bolsa(
    fecha_inicio: date,
    fecha_fin: date,
    *,
    request_fn: Optional[RequestFn] = None,
) -> list[PrecioBolsaDia]:
    """Precio de bolsa nacional (COP/kWh) por fecha en el rango [inicio, fin]."""
    fn = request_fn or _build_request_fn()
    body = {
        "MetricId": ENDPOINT_PRECIO_BOLSA,
        "StartDate": fecha_inicio.isoformat(),
        "EndDate": fecha_fin.isoformat(),
    }
    payload = fn(ENDPOINT_PRECIO_BOLSA, body)
    precios = _parse_precios(payload)
    logger.info(
        "MEM precios de bolsa %s→%s: %s días", fecha_inicio, fecha_fin, len(precios)
    )
    return precios


def get_asignaciones(
    agente: str,
    fecha_inicio: date,
    fecha_fin: date,
    *,
    request_fn: Optional[RequestFn] = None,
) -> list[AsignacionMEM]:
    """Asignaciones/energía liquidada del agente en el rango [inicio, fin]."""
    fn = request_fn or _build_request_fn()
    body = {
        "MetricId": ENDPOINT_ASIGNACIONES,
        "Agent": agente,
        "StartDate": fecha_inicio.isoformat(),
        "EndDate": fecha_fin.isoformat(),
    }
    payload = fn(ENDPOINT_ASIGNACIONES, body)
    asignaciones = _parse_asignaciones(payload)
    logger.info(
        "MEM asignaciones %s %s→%s: %s registros",
        agente, fecha_inicio, fecha_fin, len(asignaciones),
    )
    return asignaciones
