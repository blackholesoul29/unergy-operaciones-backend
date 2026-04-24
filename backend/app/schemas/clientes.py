from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class ClienteCreate(BaseModel):
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    correo_electronico: Optional[str] = None
    telefono_contacto: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteica_pct: Optional[float] = None


class ClienteUpdate(ClienteCreate):
    razon_social_nombre: Optional[str] = None


class ClienteOut(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: Optional[str]
    tipo_persona: Optional[str]
    representante_legal: Optional[str]
    correo_electronico: Optional[str]
    telefono_contacto: Optional[str]
    direccion: Optional[str]
    ciudad: Optional[str]
    iva_pct: Optional[float]
    retencion_pct: Optional[float]
    reteica_pct: Optional[float]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
