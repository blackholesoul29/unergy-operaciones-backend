from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date


class ClienteCreate(BaseModel):
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    correo_electronico: Optional[str] = None
    correo_liquidacion: Optional[str] = None
    correo_monitoreo: Optional[str] = None
    correo_soporte: Optional[str] = None
    telefono_contacto: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    banco: Optional[str] = None
    tipo_cuenta: Optional[str] = None
    numero_cuenta: Optional[str] = None
    titular_cuenta: Optional[str] = None
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteica_pct: Optional[float] = None
    rut_url: Optional[str] = None


class ClienteUpdate(ClienteCreate):
    razon_social_nombre: Optional[str] = None


class ClienteServicioCreate(BaseModel):
    tipo: str
    fecha_inicio: Optional[date] = None
    notas: Optional[str] = None


class ClienteServicioOut(ClienteServicioCreate):
    id: int
    cliente_id: int
    created_at: datetime
    model_config = {"from_attributes": True}


class ClienteDocumentoCreate(BaseModel):
    tipo: str
    nombre: str
    numero: Optional[str] = None
    fecha: Optional[date] = None
    estado: Optional[str] = "borrador"
    archivo_url: Optional[str] = None
    archivo_nombre: Optional[str] = None
    servicio_id: Optional[int] = None
    notas: Optional[str] = None


class ClienteDocumentoUpdate(BaseModel):
    nombre: Optional[str] = None
    numero: Optional[str] = None
    fecha: Optional[date] = None
    estado: Optional[str] = None
    archivo_url: Optional[str] = None
    archivo_nombre: Optional[str] = None
    servicio_id: Optional[int] = None
    notas: Optional[str] = None


class ClienteDocumentoOut(ClienteDocumentoCreate):
    id: int
    cliente_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ClienteBase(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    correo_electronico: Optional[str] = None
    correo_liquidacion: Optional[str] = None
    correo_monitoreo: Optional[str] = None
    correo_soporte: Optional[str] = None
    telefono_contacto: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    banco: Optional[str] = None
    tipo_cuenta: Optional[str] = None
    numero_cuenta: Optional[str] = None
    titular_cuenta: Optional[str] = None
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteica_pct: Optional[float] = None
    rut_url: Optional[str] = None
    origina_investment_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ClienteListOut(ClienteBase):
    pass


class ClienteOut(ClienteBase):
    servicios: list[ClienteServicioOut] = []
    documentos_comerciales: list[ClienteDocumentoOut] = []

    @field_validator("servicios", "documentos_comerciales", mode="before")
    @classmethod
    def none_to_list(cls, v):
        return v if v is not None else []
