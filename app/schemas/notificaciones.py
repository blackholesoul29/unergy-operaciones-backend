from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict


class NotificacionCreate(BaseModel):
    usuario_id: int
    tipo: Literal["alerta", "info", "accion"]
    titulo: str
    mensaje: str


class NotificacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    usuario_id: int
    tipo: str
    titulo: str
    mensaje: str
    leida: bool
    created_at: datetime
