from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


class NotificacionCreate(BaseModel):
    usuario_id: int
    tipo: Literal["alerta", "info", "accion"]
    titulo: str
    mensaje: str
    link: Optional[str] = None


class NotificacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    tipo: str
    titulo: str
    mensaje: str
    leida: bool
    link: Optional[str] = None
    created_at: datetime


# ── Notificaciones de alertas (contratos PPA) ────────────────────────────────

class NotificacionAlertaBase(BaseModel):
    titulo: str
    mensaje: str
    severidad: str = "critica"  # critica | persistente | info
    canal: str = "in_app"       # in_app | email | ambos
    alerta_ref: Optional[str] = None


class NotificacionAlertaCreate(NotificacionAlertaBase):
    usuario_id: int


class NotificacionAlertaResponse(NotificacionAlertaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    leida: bool
    email_enviado: bool
    created_at: datetime
    leida_at: Optional[datetime] = None


class NotificacionAlertaMarkRead(BaseModel):
    ids: list[int]
