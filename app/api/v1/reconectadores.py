"""Reconectadores — estado y comandos ON/OFF del relay via Solenium."""
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
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("reconectadores")
router = APIRouter(prefix="/reconectadores", tags=["Reconectadores"])

_SOLENIUM_AUTH_URL  = "https://auth.solenium.co/api/token/"
_SOLENIUM_RELAY_SET = "https://data.solenium.co/api/project/{sol_id}/relay/set-status/"
_SOLENIUM_RELAY_GET = "https://data.solenium.co/api/project/{sol_id}/relay/"

# Cliente interno (usa credenciales de Railway — no necesita creds del usuario)
_client: SoleniumClient | None = None

def _get_client() -> SoleniumClient:
    global _client
    if _client is None:
        _client = SoleniumClient()
    if not _client.enabled:
        raise HTTPException(503, "Solenium no configurado en el servidor")
    return _client


# ── Schemas ────────────────────────────────────────────────────────────────────

class ComandoRequest(BaseModel):
    username:         str
    password:         str
    accion:           Literal["ON", "OFF"]
    is_interrogating: bool = True


class ComandoResponse(BaseModel):
    success: bool
    message: str
    accion:  str
    detail:  str | None = None


class RelayEstado(BaseModel):
    proyecto_id: int
    nombre:      str
    sol_id:      int
    active:      bool | None   # True=ON, False=OFF, None=sin dato


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_user_token(username: str, password: str) -> str:
    """Autentica con credenciales del usuario y retorna JWT."""
    try:
        with httpx.Client(timeout=15) as c:
            resp = c.post(_SOLENIUM_AUTH_URL,
                          json={"username": username, "password": password})
    except Exception as exc:
        raise HTTPException(503, f"No se pudo conectar a Solenium: {exc}") from exc

    if resp.status_code == 401:
        raise HTTPException(401, "Credenciales Solenium incorrectas")
    if resp.status_code not in (200, 201):
        raise HTTPException(502, f"Solenium auth → HTTP {resp.status_code}")

    token = resp.json().get("access")
    if not token:
        raise HTTPException(502, "Solenium no devolvió token")
    return token


def _fetch_relay_estado(sol_id: int, client: SoleniumClient) -> bool | None:
    """
    Llama GET /project/{sol_id}/relay/ y retorna el campo `active`.
    Usa el cliente interno (credenciales del servidor).
    """
    url = _SOLENIUM_RELAY_GET.format(sol_id=sol_id)
    try:
        data = client._get(url)          # usa el mismo helper con retry/token
        if data is None:
            return None
        val = data.get("active")
        if val is None:
            return None
        return bool(val)
    except Exception as exc:
        logger.warning("relay_get sol_id=%d error=%s", sol_id, exc)
        return None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/estados", response_model=list[RelayEstado])
def get_estados(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Retorna el estado real del relay (campo `active`) de cada proyecto
    consultando directamente Solenium con las credenciales del servidor.
    No requiere credenciales del usuario.
    """
    client = _get_client()

    proyectos = db.query(Proyecto).filter(
        Proyecto.estado == "en_operacion",
        Proyecto.project_id_solenium.isnot(None),
        Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
        Proyecto.srv_operacion == True,  # noqa: E712
    ).all()

    if not proyectos:
        return []

    def _query(p):
        sol_id = int(p.project_id_solenium)
        active = _fetch_relay_estado(sol_id, client)
        return RelayEstado(
            proyecto_id=p.id,
            nombre=p.nombre_comercial,
            sol_id=sol_id,
            active=active,
        )

    with ThreadPoolExecutor(max_workers=8) as ex:
        resultados = list(ex.map(_query, proyectos))

    return resultados


@router.post("/{proyecto_id}/comando", response_model=ComandoResponse)
def enviar_comando(
    proyecto_id: int,
    body: ComandoRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Autentica con Solenium usando las credenciales del body y envía
    un comando ON/OFF al relay de la planta.
    Las credenciales se validan en cada llamada — nunca se almacenan.
    """
    proyecto = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")
    if not proyecto.project_id_solenium:
        raise HTTPException(422, "Este proyecto no tiene ID de Solenium configurado")

    sol_id = int(proyecto.project_id_solenium)
    token  = _get_user_token(body.username, body.password)

    url = _SOLENIUM_RELAY_SET.format(sol_id=sol_id)
    try:
        with httpx.Client(timeout=30) as c:
            resp = c.post(
                url,
                json={"status_to_set": body.accion,
                      "is_interrogating": body.is_interrogating},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:
        raise HTTPException(503, f"Error de conexión: {exc}") from exc

    logger.info("relay_cmd proyecto=%d sol_id=%d accion=%s user=%s http=%s",
                proyecto_id, sol_id, body.accion, body.username, resp.status_code)

    if resp.status_code < 300:
        return ComandoResponse(
            success=True,
            message=f"Comando {body.accion} enviado a {proyecto.nombre_comercial}",
            accion=body.accion,
            detail=resp.text[:200],
        )

    raise HTTPException(502,
        detail=f"Solenium → HTTP {resp.status_code}: {resp.text[:120]}")
