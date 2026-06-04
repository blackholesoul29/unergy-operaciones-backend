"""Reconectadores — comandos ON/OFF al relay de cada planta via Solenium."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.proyectos import Proyecto, TipoProyectoEnum

logger = logging.getLogger("reconectadores")
router = APIRouter(prefix="/reconectadores", tags=["Reconectadores"])

_SOLENIUM_AUTH_URL   = "https://auth.solenium.co/api/token/"
_SOLENIUM_RELAY_URL  = "https://data.solenium.co/api/project/{sol_id}/relay/set-status/"
_SOLENIUM_STATUS_URLS = [
    "https://data.solenium.co/api/project/{sol_id}/relay/",
    "https://data.solenium.co/api/project/{sol_id}/relay/status/",
    "https://data.solenium.co/api/project_detail/{sol_id}/",
]


# ── Schemas ────────────────────────────────────────────────────────────────────

class ComandoRequest(BaseModel):
    username:         str
    password:         str
    accion:           Literal["ON", "OFF"]
    is_interrogating: bool = True


class ComandoResponse(BaseModel):
    success:  bool
    message:  str
    accion:   str
    detail:   str | None = None


class SyncRequest(BaseModel):
    username: str
    password: str


class EstadoProyecto(BaseModel):
    proyecto_id: int
    nombre:      str
    sol_id:      int
    estado:      str | None   # "ON" | "OFF" | None si no se pudo leer
    raw:         dict | None = None


class SyncResponse(BaseModel):
    proyectos: list[EstadoProyecto]
    advertencia: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_solenium_token(username: str, password: str) -> str:
    """Autentica contra Solenium y retorna el JWT de acceso."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                _SOLENIUM_AUTH_URL,
                json={"username": username, "password": password},
            )
    except Exception as exc:
        raise HTTPException(503, f"No se pudo conectar a Solenium: {exc}") from exc

    if resp.status_code == 401:
        raise HTTPException(401, "Credenciales Solenium incorrectas")
    if resp.status_code not in (200, 201):
        raise HTTPException(502, f"Solenium auth → HTTP {resp.status_code}: {resp.text[:120]}")

    token = resp.json().get("access")
    if not token:
        raise HTTPException(502, "Solenium no devolvió token de acceso")
    return token


def _send_relay(sol_id: int, accion: str, is_interrogating: bool, token: str) -> dict:
    """Envía el comando al relay de la planta."""
    url = _SOLENIUM_RELAY_URL.format(sol_id=sol_id)
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                url,
                json={"status_to_set": accion, "is_interrogating": is_interrogating},
                headers={"Authorization": f"Bearer {token}"},
            )
        return {"status_code": resp.status_code, "body": resp.text[:300], "ok": resp.status_code < 300}
    except Exception as exc:
        return {"status_code": 0, "body": str(exc), "ok": False}


def _parse_relay_estado(data: dict) -> str | None:
    """
    Intenta extraer el estado ON/OFF del payload de Solenium.
    Prueba varios campos conocidos según la versión de la API.
    """
    if not data:
        return None
    # Campos directos
    for key in ("status", "relay_status", "state", "current_status",
                "status_to_set", "relay_state", "value"):
        val = data.get(key)
        if isinstance(val, str) and val.upper() in ("ON", "OFF"):
            return val.upper()
        if isinstance(val, bool):
            return "ON" if val else "OFF"
    # Anidado en relay{}
    relay = data.get("relay") or data.get("relay_info") or {}
    if isinstance(relay, dict):
        for key in ("status", "state", "current_status", "value"):
            val = relay.get(key)
            if isinstance(val, str) and val.upper() in ("ON", "OFF"):
                return val.upper()
    return None


def _fetch_relay_status(sol_id: int, token: str) -> tuple[str | None, dict | None]:
    """
    Consulta el estado actual del relay probando múltiples endpoints.
    Retorna (estado, raw_data).
    """
    headers = {"Authorization": f"Bearer {token}"}
    for url_tpl in _SOLENIUM_STATUS_URLS:
        url = url_tpl.format(sol_id=sol_id)
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json() if resp.text else {}
                estado = _parse_relay_estado(data)
                if estado:
                    return estado, data
                # Devolvió 200 pero no pudimos parsear el estado
                return None, data
        except Exception:
            continue
    return None, None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/{proyecto_id}/comando", response_model=ComandoResponse)
def enviar_comando(
    proyecto_id: int,
    body: ComandoRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Autentica con Solenium usando las credenciales del body y envía
    un comando ON/OFF al relay de la planta indicada.

    Requiere que el proyecto tenga project_id_solenium configurado.
    Las credenciales se validan en cada llamada (no se almacenan).
    """
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")
    if not proyecto.project_id_solenium:
        raise HTTPException(422, "Este proyecto no tiene ID de Solenium configurado")

    sol_id = int(proyecto.project_id_solenium)

    # 1 — autenticar
    token = _get_solenium_token(body.username, body.password)

    # 2 — enviar comando
    result = _send_relay(sol_id, body.accion, body.is_interrogating, token)

    logger.info(
        "relay_cmd proyecto=%d sol_id=%d accion=%s user=%s http=%s",
        proyecto_id, sol_id, body.accion, body.username, result["status_code"],
    )

    if result["ok"]:
        return ComandoResponse(
            success=True,
            message=f"Comando {body.accion} enviado correctamente a {proyecto.nombre_comercial}",
            accion=body.accion,
            detail=result["body"],
        )

    raise HTTPException(
        502,
        detail=f"Solenium respondió HTTP {result['status_code']}: {result['body']}",
    )


@router.post("/sync-estados", response_model=SyncResponse)
def sync_estados(
    body: SyncRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Consulta el estado real ON/OFF del relay de cada planta directamente
    desde Solenium. Útil para sincronizar la vista con el estado real.

    Requiere credenciales Solenium válidas.
    Consulta todos los proyectos en operación con project_id_solenium configurado.
    """
    token = _get_solenium_token(body.username, body.password)

    proyectos = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
        Proyecto.project_id_solenium.isnot(None),
        Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
        Proyecto.srv_operacion == True,  # noqa: E712
    ).all()

    if not proyectos:
        return SyncResponse(proyectos=[], advertencia="No hay proyectos configurados")

    def _query_one(p):
        sol_id = int(p.project_id_solenium)
        estado, raw = _fetch_relay_status(sol_id, token)
        return EstadoProyecto(
            proyecto_id=p.id,
            nombre=p.nombre_comercial,
            sol_id=sol_id,
            estado=estado,
            raw=raw,
        )

    with ThreadPoolExecutor(max_workers=8) as ex:
        resultados = list(ex.map(_query_one, proyectos))

    sin_dato = sum(1 for r in resultados if r.estado is None)
    advertencia = None
    if sin_dato == len(resultados):
        advertencia = "Solenium no expone el estado del relay via GET — solo se puede escribir (ON/OFF). El estado mostrado viene del historial de esta app."
    elif sin_dato > 0:
        advertencia = f"{sin_dato} proyecto(s) sin dato de relay en Solenium."

    logger.info("sync_estados user=%s proyectos=%d sin_dato=%d", body.username, len(resultados), sin_dato)
    return SyncResponse(proyectos=resultados, advertencia=advertencia)
