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


class ContactoParaClienteCreate(BaseModel):
    """Contacto a crear junto con el cliente (ver create_cliente). Definida acá
    (no reutiliza ContactoCreate de schemas/proyectos) para evitar un import
    circular: schemas/proyectos.py ya importa _EMAIL_RE desde este archivo."""
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    email: str
    tipo: str = "comercial"

    @field_validator("email")
    @classmethod
    def email_valido(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("email inválido")
        return v


class TasaServicioUpsert(BaseModel):
    servicio: str  # Representación | CGM | Administración
    proyecto_id: Optional[int] = None  # None = todos los proyectos del cliente
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteiva_pct: Optional[float] = None
    reteica_pct: Optional[float] = None


class TasaServicioOut(TasaServicioUpsert):
    id: int
    cliente_id: int
    model_config = {"from_attributes": True}


class ClienteServicioCreate(BaseModel):
    tipo: str
    fecha_inicio: Optional[date] = None
    notas: Optional[str] = None


class ClienteServicioOut(ClienteServicioCreate):
    id: int
    cliente_id: int
    created_at: datetime
    model_config = {"from_attributes": True}


class ClienteCreate(BaseModel):
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    correo_liquidacion: Optional[str] = None
    correo_monitoreo: Optional[str] = None
    correo_soporte: Optional[str] = None
    correo_operacional: Optional[str] = None
    correos_operacionales: list[str] = []
    correos_cgm: list[str] = []
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
    reteiva_pct: Optional[float] = None
    rut_url: Optional[str] = None
    origen_tipo: Optional[str] = None
    origen_detalle: Optional[str] = None
    contactos: list[ContactoParaClienteCreate] = []
    servicios: list[ClienteServicioCreate] = []

    @field_validator("correos_operacionales", "correos_cgm", mode="before")
    @classmethod
    def validate_correos(cls, v):
        return _validate_email_list(v or [])


class ClienteUpdate(ClienteCreate):
    razon_social_nombre: Optional[str] = None


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
    oportunidad_id: Optional[int] = None


class ClienteDocumentoUpdate(BaseModel):
    nombre: Optional[str] = None
    numero: Optional[str] = None
    fecha: Optional[date] = None
    estado: Optional[str] = None
    archivo_url: Optional[str] = None
    archivo_nombre: Optional[str] = None
    servicio_id: Optional[int] = None
    notas: Optional[str] = None
    oportunidad_id: Optional[int] = None


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
    correo_liquidacion: Optional[str] = None
    correo_monitoreo: Optional[str] = None
    correo_soporte: Optional[str] = None
    correo_operacional: Optional[str] = None
    correos_operacionales: list[str] = []
    correos_cgm: list[str] = []
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
    reteiva_pct: Optional[float] = None
    rut_url: Optional[str] = None
    origina_investment_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ClienteListOut(ClienteBase):
    pass


class ClienteOut(ClienteBase):
    origen_tipo: Optional[str] = None
    origen_detalle: Optional[str] = None
    servicios: list[ClienteServicioOut] = []
    documentos_comerciales: list[ClienteDocumentoOut] = []

    @field_validator("servicios", "documentos_comerciales", "correos_operacionales", "correos_cgm", mode="before")
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
