"""Recuperación de datos de medidor vía WebSocket de Quoia -- le pide al
medidor físico que reenvíe sus lecturas para un rango de fechas, rellenando
huecos de telemetría. Distinto de GaiaClient, que solo LEE lo que ya está
guardado en Quoia: esto dispara una interrogación real sobre el equipo.

Puerto de process/src/internals/recuperacion_quoia.py (repo Reporte-Energia).

Protocolo descubierto vía DevTools (no hay documentación oficial de Quoia):
  wss://gaia.quoia.energy/ws/recovery/
  Enviar:  {"meter_id": int, "init_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
  Recibir: uno o más {"status": ..., "progress": 0-100, "value": ...}

  meter_id es el ID administrativo del medidor (main_meter/backup_meter del
  border de Quoia) -- NO es el node_id usado para /measurements/.

  No se observó autenticación en el handshake -- puede cambiar sin aviso al
  ser un endpoint interno no documentado.
"""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

logger = logging.getLogger("reporte_energia.recuperacion")

RECOVERY_WS_URL = "wss://gaia.quoia.energy/ws/recovery/"
TIMEOUT_SEGUNDOS = 90


async def _recuperar_async(meter_id: int, init_date: str, end_date: str) -> dict | None:
    ultimo = None
    try:
        async with websockets.connect(RECOVERY_WS_URL, open_timeout=30) as ws:
            await ws.send(json.dumps({
                "meter_id": meter_id,
                "init_date": init_date,
                "end_date": end_date,
            }))
            try:
                async with asyncio.timeout(TIMEOUT_SEGUNDOS):
                    async for mensaje in ws:
                        ultimo = json.loads(mensaje)
                        logger.info("recuperacion meter_id=%s progress=%s status=%s",
                                    meter_id, ultimo.get("progress"), ultimo.get("status"))
                        if ultimo.get("progress") == 100:
                            break
            except TimeoutError:
                logger.warning("recuperacion meter_id=%s timeout tras %ss", meter_id, TIMEOUT_SEGUNDOS)
    except (websockets.exceptions.WebSocketException, OSError) as e:
        # La conexión puede caerse a mitad de la interrogación -- sin este
        # catch, una sola falla de red tumbaría el pipeline completo en vez
        # de tratarse como una recuperación fallida más.
        logger.warning("recuperacion meter_id=%s error de conexión: %s", meter_id, e)

    return ultimo


def recuperar_datos_medidor(meter_id: int, init_date: str, end_date: str) -> dict | None:
    """Interroga al medidor `meter_id` para que reenvíe lecturas entre
    init_date y end_date ('YYYY-MM-DD'). Bloqueante (corre su propio loop de
    asyncio). Retorna el último mensaje recibido, o None si no llegó ninguno
    (incluye fallas de conexión -- nunca propaga la excepción)."""
    return asyncio.run(_recuperar_async(meter_id, init_date, end_date))


def fue_exitosa(resultado: dict | None) -> bool:
    return bool(resultado and resultado.get("status") == "success")
