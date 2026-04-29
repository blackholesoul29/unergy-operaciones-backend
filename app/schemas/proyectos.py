from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date


# ── Inversionistas ────────────────────────────────────────────────────────────

class ProyectoInversionistaCreate(BaseModel):
    cliente_id: int
    porcentaje_participacion: Optional[float] = None
    es_patrimonio_autonomo: bool = False
    contrato_ref: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


class ProyectoInversionistaUpdate(BaseModel):
    porcentaje_participacion: Optional[float] = None
    es_patrimonio_autonomo: Optional[bool] = None
    contrato_ref: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


class ProyectoInversionistaOut(ProyectoInversionistaCreate):
    id: int
    proyecto_id: int
    cliente_nombre: str = ""
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ── Info Técnica ──────────────────────────────────────────────────────────────

class ProyectoInfoTecnicaCreate(BaseModel):
    cantidad_total_paneles: Optional[int] = None
    tiene_almacenamiento: bool = False
    capacidad_almacenamiento_kwh: Optional[float] = None
    marca_almacenamiento: Optional[str] = None
    modelo_almacenamiento: Optional[str] = None


class ProyectoInfoTecnicaOut(ProyectoInfoTecnicaCreate):
    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Grupos Panel ──────────────────────────────────────────────────────────────

class ProyectoGrupoPanelCreate(BaseModel):
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_pico_wp: Optional[float] = None
    cantidad: Optional[int] = None


class ProyectoGrupoPanelUpdate(BaseModel):
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_pico_wp: Optional[float] = None
    cantidad: Optional[int] = None


class ProyectoGrupoPanelOut(ProyectoGrupoPanelCreate):
    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Inversores ────────────────────────────────────────────────────────────────

class ProyectoInversorCreate(BaseModel):
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_nominal_kw: Optional[float] = None
    numero_serie: Optional[str] = None
    tipo: Optional[str] = None


class ProyectoInversorUpdate(BaseModel):
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_nominal_kw: Optional[float] = None
    numero_serie: Optional[str] = None
    tipo: Optional[str] = None


class ProyectoInversorOut(ProyectoInversorCreate):
    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Contactos ─────────────────────────────────────────────────────────────────

class ProyectoContactoCreate(BaseModel):
    nombre: str
    email: str
    tipo: Optional[str] = None
    recibe_notificaciones: bool = True


class ProyectoContactoUpdate(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    tipo: Optional[str] = None
    recibe_notificaciones: Optional[bool] = None


class ProyectoContactoOut(ProyectoContactoCreate):
    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Proyecto principal ────────────────────────────────────────────────────────

class ProyectoCreate(BaseModel):
    nombre_comercial: str
    cliente_id: int
    portafolio_id: Optional[int] = None
    proyecto_padre_id: Optional[int] = None
    nombre_bitacora: Optional[str] = None
    nombre_clientes: Optional[str] = None
    topic_slug: Optional[str] = None
    sub_project: Optional[str] = None
    clasificacion_regulatoria: Optional[str] = None
    tipo_tecnologia: Optional[str] = None
    tipo_proyecto: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    potencia_con_cen_mw: Optional[float] = None
    cantidad_total_paneles: Optional[int] = None
    produccion_especifica_kwh_kwp: Optional[float] = None
    codigo_cnd: Optional[str] = None
    estado: Optional[str] = "en_desarrollo"
    fecha_entrada_operacion: Optional[date] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    direccion_vereda: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    tipo_conexion: Optional[str] = None
    operador_red: Optional[str] = None
    project_id_solenium: Optional[str] = None
    carpeta_drive_codigo: Optional[str] = None
    estado_resultados_url: Optional[str] = None
    income_distribution_method: Optional[str] = None
    generar_liquidacion: Optional[bool] = None
    p90_mensual_kwh: Optional[str] = None
    p50_mensual_kwh: Optional[str] = None
    codigo_tsf: Optional[str] = None


class ProyectoUpdate(ProyectoCreate):
    nombre_comercial: Optional[str] = None
    cliente_id: Optional[int] = None


class ProyectoOut(BaseModel):
    id: int
    nombre_comercial: str
    cliente_id: int
    portafolio_id: Optional[int]
    proyecto_padre_id: Optional[int]
    nombre_bitacora: Optional[str]
    nombre_clientes: Optional[str]
    topic_slug: Optional[str]
    sub_project: Optional[str]
    clasificacion_regulatoria: Optional[str]
    tipo_tecnologia: Optional[str]
    tipo_proyecto: Optional[str]
    potencia_instalada_kwp: Optional[float]
    potencia_con_cen_mw: Optional[float]
    cantidad_total_paneles: Optional[int]
    produccion_especifica_kwh_kwp: Optional[float]
    codigo_cnd: Optional[str]
    estado: str
    fecha_entrada_operacion: Optional[date]
    departamento: Optional[str]
    municipio: Optional[str]
    direccion_vereda: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    tipo_conexion: Optional[str]
    operador_red: Optional[str]
    project_id_solenium: Optional[str]
    carpeta_drive_codigo: Optional[str]
    estado_resultados_url: Optional[str]
    income_distribution_method: Optional[str]
    generar_liquidacion: bool
    p90_mensual_kwh: Optional[str] = None
    p50_mensual_kwh: Optional[str] = None
    codigo_tsf: Optional[str] = None
    srv_operacion: bool
    srv_representacion: bool
    srv_cgm: bool
    srv_ppa: bool
    srv_promotor: bool
    srv_rec: bool
    inversionistas: list[ProyectoInversionistaOut] = []
    info_tecnica: Optional[ProyectoInfoTecnicaOut] = None
    grupos_panel: list[ProyectoGrupoPanelOut] = []
    inversores: list[ProyectoInversorOut] = []
    contactos: list[ProyectoContactoOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("inversionistas", "grupos_panel", "inversores", "contactos", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            return list(v) if hasattr(v, "__iter__") else [v]
        return v
