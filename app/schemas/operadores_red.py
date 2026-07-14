import re
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OperadorRedContactoCreate(BaseModel):
    email: str
    nombre: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        addr = v.strip().lower()
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Dirección de correo inválida: {addr}")
        return addr


class OperadorRedContactoUpdate(BaseModel):
    email: Optional[str] = None
    nombre: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if v is None:
            return v
        addr = v.strip().lower()
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Dirección de correo inválida: {addr}")
        return addr


class OperadorRedContactoOut(BaseModel):
    id: int
    email: str
    nombre: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class OperadorRedOut(BaseModel):
    id: int
    nombre_legal: str
    nombre_comercial: Optional[str] = None
    contactos: list[OperadorRedContactoOut] = []
    fronteras_vinculadas: int = 0
    model_config = {"from_attributes": True}
