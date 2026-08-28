import re
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteica_pct: Optional[float] = None
    reteiva_pct: Optional[float] = None
    origen_tipo: Optional[str] = None
    origen_detalle: Optional[str] = None
    contactos: list[ContactoParaClienteCreate] = []
    servicios: list[ClienteServicioCreate] = []


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
    # Nullable desde la generalizacion (migracion 122): un documento puede
    # pertenecer a un ContratoServicio o un PPAContrato en vez de a un Cliente.
    cliente_id: Optional[int] = None
    contrato_servicio_id: Optional[int] = None
    ppa_contrato_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ClienteBase(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    tipo_persona: Optional[str] = None
    representante_legal: Optional[str] = None
    direccion: Optional[str] = None
    ciudad: Optional[str] = None
    departamento: Optional[str] = None
    iva_pct: Optional[float] = None
    retencion_pct: Optional[float] = None
    reteica_pct: Optional[float] = None
    reteiva_pct: Optional[float] = None
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

    @field_validator("servicios", "documentos_comerciales", mode="before")
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
