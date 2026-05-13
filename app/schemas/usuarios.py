from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.usuarios import RolEnum


class UsuarioOut(BaseModel):
    id: int
    email: str
    nombre: str
    rol: RolEnum
    activo: bool
    ultimo_acceso: Optional[datetime]

    model_config = {"from_attributes": True}


class UsuarioCreate(BaseModel):
    email: EmailStr
    nombre: str
    rol: RolEnum = RolEnum.admin
    password: str
    activo: bool = True


class UsuarioUpdate(BaseModel):
    nombre: str | None = None
    rol: RolEnum | None = None
    activo: bool | None = None
    password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
