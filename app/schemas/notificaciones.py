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
