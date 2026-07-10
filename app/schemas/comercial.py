from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

OrigenClienteLiteral = Literal["prospeccion_propia", "recomendacion", "referido", "otro"]
EstadoOportunidadLiteral = Literal["prospeccion", "oferta", "negociacion", "fin"]
TipoServicioLiteral = Literal["representacion", "comunidad_energetica"]
TipoGestionLiteral = Literal["llamada", "correo", "reunion", "whatsapp", "nota"]
# Tipos válidos del modelo Contacto existente (TipoContactoEnum).
TipoContactoLiteral = Literal["liquidacion", "operacional", "comercial", "cgm", "contable"]


class ContactoNuevoIn(BaseModel):
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    email: str = Field(min_length=3)
    tipo: TipoContactoLiteral = "comercial"

    @field_validator("email")
    @classmethod
    def email_valido(cls, v: str) -> str:
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("email inválido")
        return v.strip().lower()


class ClienteNuevoIn(BaseModel):
    razon_social_nombre: str = Field(min_length=1)
    nit_cedula: Optional[str] = None
    origen_tipo: Optional[OrigenClienteLiteral] = None
    origen_detalle: Optional[str] = None
    contactos: list[ContactoNuevoIn] = Field(min_length=1)


class OportunidadCreate(BaseModel):
    """Exactamente uno de cliente_id (existente) o cliente_nuevo."""
    cliente_id: Optional[int] = None
    cliente_nuevo: Optional[ClienteNuevoIn] = None
    nombre: Optional[str] = None
    tipo_servicio: Optional[TipoServicioLiteral] = None
    notas: Optional[str] = None

    @model_validator(mode="after")
    def exactamente_un_cliente(self):
        if bool(self.cliente_id) == bool(self.cliente_nuevo):
            raise ValueError("Envía cliente_id O cliente_nuevo (exactamente uno)")
        return self


class OportunidadUpdate(BaseModel):
    # `estado` NO es editable por PATCH (usar POST /{id}/estado).
    nombre: Optional[str] = None
    tipo_servicio: Optional[TipoServicioLiteral] = None
    numero_oferta: Optional[str] = None
    fecha_tentativa_inicio_representacion: Optional[date] = None
    fecha_tentativa_inicio_compra_energia: Optional[date] = None
    fecha_estimada_firma: Optional[date] = None
    notas: Optional[str] = None


class EstadoChangeIn(BaseModel):
    estado: EstadoOportunidadLiteral


class GestionCreate(BaseModel):
    tipo: TipoGestionLiteral
    descripcion: str = Field(min_length=1)
    fecha: Optional[datetime] = None


class ProyectoDesdeCRMIn(BaseModel):
    nombre_comercial: str = Field(min_length=1)
    potencia_instalada_kwp: Optional[float] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    # OBLIGATORIO — validación bloqueante del CRM (spec §4.2).
    operador_red_id: int
