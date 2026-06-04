import re
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def _validate_email_list(v: list) -> list:
    """Validate each address in the list and return trimmed, lowercase entries."""
    if not v:
        return []
    result = []
    for raw in v:
        addr = str(raw).strip().lower()
        if not addr:
            continue
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Dirección de correo inválida: {addr}")
        result.append(addr)
    return result


class ClienteCreate(BaseModel):
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    correo_electronico: Optional[str] = None
    correo_liquidacion: Optional[str] = None
    correo_monitoreo: Optional[str] = None
    correo_soporte: Optional[str] = None
    correo_operacional: Optional[str] = None
    correos_operacionales: list[str] = []
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

    @field_validator("correos_operacionales", mode="before")
    @classmethod
    def validate_correos(cls, v):
        return _validate_email_list(v or [])


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
    correo_operacional: Optional[str] = None
    correos_operacionales: list[str] = []
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

    @field_validator("servicios", "documentos_comerciales", "correos_operacionales", mode="before")
    @classmethod
    def none_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        # SQLAlchemy InstrumentedList o cualquier iterable
        try:
            return list(v)
        except TypeError:
            return []
