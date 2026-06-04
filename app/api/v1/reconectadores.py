"""Reconectadores — comandos ON/OFF al relay de cada planta via Solenium."""
from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.proyectos import Proyecto

logger = logging.getLogger("reconectadores")
router = APIRouter(prefix="/reconectadores", tags=["Reconectadores"])

_SOLENIUM_AUTH_URL  = "https://auth.solenium.co/api/token/"
_SOLENIUM_RELAY_URL = "https://data.solenium.co/api/project/{sol_id}/relay/set-status/"


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
