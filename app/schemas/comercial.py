from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

OrigenClienteLiteral = Literal["prospeccion_propia", "recomendacion", "referido", "otro"]
# Pipeline de la oferta (2026-08-02). Antes vivía en la oportunidad y se llamaba
# prospeccion / envio_oferta / negociacion_contrato.
EstadoComercialLiteral = Literal[
    "oportunidad", "oferta", "contrato", "firmado", "operando", "terminado", "declinado"
]
EstadoOportunidadLiteral = EstadoComercialLiteral  # alias de compatibilidad
TipoServicioLiteral = Literal["representacion", "comunidad_energetica"]
TipoOfertaLiteral = Literal["servicios_operacionales", "compra_energia", "comunidad_energetica"]
ResultadoOfertaLiteral = Literal["pendiente", "aceptado", "declinado"]
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
    forzar_cliente_duplicado: bool = Field(
        False, description="true: crear cliente_nuevo igual aunque exista uno con nombre muy parecido"
    )

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


class PrecioAnualIn(BaseModel):
    """Una fila de la tabla de precios de la oferta: año de suministro y $COP/kWh.
    Al firmar se expande a 12 filas de `ppa_tarifas` (una por mes)."""
    anio: int = Field(ge=2000, le=2100)
    precio: float = Field(gt=0)


class FirmarOfertaIn(BaseModel):
    """Convierte una oferta aceptada en su contrato y la mueve a 'firmado'.

    Las condiciones NO se guardan en la oferta: alimentan el contrato PPA
    (o de representación), que es donde ya viven y donde las leen Cumplimiento
    y Liquidaciones. La oferta solo se queda con el enlace.
    """
    numero_codigo_contrato: Optional[str] = None
    nombre_interno: Optional[str] = None
    fecha_inicio: date
    fecha_fin: date
    # Tarifa única cuando no hay tabla por año (Bayunca: 300 $/kWh planos).
    tarifa_base: Optional[float] = Field(None, gt=0)
    precios_anuales: Optional[list[PrecioAnualIn]] = None
    indice_indexacion: Optional[str] = None
    # Mes base de indexación en formato YYYY-MM, como lo guarda ppa_contratos.
    periodo_indexacion_base: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    cantidad_minima_kwh_mes: Optional[float] = Field(None, ge=0)
    carpeta_link: Optional[str] = None

    @model_validator(mode="after")
    def coherente(self):
        if self.fecha_fin < self.fecha_inicio:
            raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")
        if not self.tarifa_base and not self.precios_anuales:
            raise ValueError("envía tarifa_base o precios_anuales")
        if self.precios_anuales:
            anios = [p.anio for p in self.precios_anuales]
            if len(anios) != len(set(anios)):
                raise ValueError("la tabla de precios tiene años repetidos")
        return self


class OfertaCreate(BaseModel):
    tipo: TipoOfertaLiteral
    planta_nombre: Optional[str] = None
    proyecto_id: Optional[int] = None
    numero_oferta: Optional[str] = None
    precio_detalle: Optional[str] = None
    # `resultado` ya no se envía: se deriva de `estado` (ver estado_a_resultado).
    estado: EstadoComercialLiteral = "oportunidad"
    etapa_texto: Optional[str] = None
    fecha_oferta: Optional[date] = None
    fecha_tentativa_inicio: Optional[date] = None
    contrato_firmado: Optional[str] = None
    detalle: Optional[dict] = None
    # ── Ficha operativa declarada (2026-08-03) ───────────────────────────────
    # Solo aplican cuando la planta no existe como Proyecto: si lo tiene, manda
    # el Proyecto (ver ficha_operativa). Editables porque si no, el equipo no
    # puede llenarlos nunca.
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    operador_red_id: Optional[int] = None
    energia_promedio_kwh_mes: Optional[float] = Field(None, ge=0)
    notas: Optional[str] = None


class OfertaUpdate(BaseModel):
    tipo: Optional[TipoOfertaLiteral] = None
    planta_nombre: Optional[str] = None
    proyecto_id: Optional[int] = None
    numero_oferta: Optional[str] = None
    precio_detalle: Optional[str] = None
    # El estado se cambia por POST /ofertas/{id}/estado, que además deja histórico.
    etapa_texto: Optional[str] = None
    fecha_oferta: Optional[date] = None
    fecha_tentativa_inicio: Optional[date] = None
    contrato_firmado: Optional[str] = None
    detalle: Optional[dict] = None
    # Ficha operativa declarada — ver OfertaCreate.
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    operador_red_id: Optional[int] = None
    energia_promedio_kwh_mes: Optional[float] = Field(None, ge=0)
    notas: Optional[str] = None


class EstadoChangeIn(BaseModel):
    estado: EstadoComercialLiteral


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
