from pydantic import BaseModel, field_validator
from typing import Optional, Literal
from datetime import datetime, date
from app.schemas.clientes import _EMAIL_RE


# ── Inversionistas ────────────────────────────────────────────────────────────

class ProyectoInversionistaCreate(BaseModel):
    cliente_id: int
    porcentaje_participacion: Optional[float] = None
    es_patrimonio_autonomo: bool = False
    contrato_ref: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None

    @field_validator("porcentaje_participacion")
    @classmethod
    def validar_porcentaje(cls, v):
        if v is not None and not (0 <= v <= 1):
            raise ValueError("El porcentaje de participación debe estar entre 0 y 1 (equivale a 0%–100%)")
        return v


class ProyectoInversionistaUpdate(BaseModel):
    porcentaje_participacion: Optional[float] = None
    es_patrimonio_autonomo: Optional[bool] = None
    contrato_ref: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None

    @field_validator("porcentaje_participacion")
    @classmethod
    def validar_porcentaje(cls, v):
        if v is not None and not (0 <= v <= 1):
            raise ValueError("El porcentaje de participación debe estar entre 0 y 1 (equivale a 0%–100%)")
        return v


class ProyectoInversionistaOut(ProyectoInversionistaCreate):
    id: int
    proyecto_id: int
    cliente_nombre: str = ""
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ── Info Técnica ──────────────────────────────────────────────────────────────

class ProyectoInfoTecnicaCreate(BaseModel):
    # Eléctrico general
    voltaje_red: Optional[str] = None
    potencia_ac_kw: Optional[float] = None
    capacidad_instalada_kwp: Optional[float] = None
    tipo_tracker: Optional[str] = None
    # Paneles
    cantidad_total_paneles: Optional[int] = None
    potencia_panel_kwp: Optional[str] = None
    marca_paneles: Optional[str] = None
    # Inversores
    cantidad_inversores: Optional[int] = None
    potencia_inversores_kwp: Optional[str] = None
    marca_inversores: Optional[str] = None
    cantidad_strings: Optional[int] = None
    # Marcas de equipos
    marca_transformador: Optional[str] = None
    marca_reconectador_rele: Optional[str] = None
    marca_totalizador: Optional[str] = None
    marca_seguidor_solar: Optional[str] = None
    marca_medidores_frontera: Optional[str] = None
    marca_modem_reconectador: Optional[str] = None
    marca_modems_frontera: Optional[str] = None
    ip_modem_reconectador: Optional[str] = None
    # Ubicación
    url_ubicacion: Optional[str] = None
    # RETIE — enlace al documento (Google Drive u otro)
    retie_url: Optional[str] = None
    # CCTV y seguridad
    cctv_estado: Optional[str] = None
    marca_cctv: Optional[str] = None
    seguridad_fisica: Optional[str] = None
    tiene_internet: Optional[str] = None
    # Almacenamiento
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
    nombre: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_nominal_kw: Optional[float] = None
    numero_serie: Optional[str] = None
    tipo: Optional[str] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class ProyectoInversorUpdate(BaseModel):
    nombre: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    potencia_nominal_kw: Optional[float] = None
    numero_serie: Optional[str] = None
    tipo: Optional[str] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None


class ProyectoInversorOut(ProyectoInversorCreate):
    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Contactos (siempre de Cliente) ────────────────────────────────────────────
# Usado por /clientes/{id}/contactos -- el endpoint fija cliente_id.

TipoContacto = Literal["operacional", "cgm", "liquidacion", "comercial", "contable"]


class ContactoCreate(BaseModel):
    nombre: Optional[str] = None
    email: str
    telefono: Optional[str] = None
    tipo: TipoContacto
    recibe_notificaciones: bool = True

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        addr = v.strip().lower()
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Dirección de correo inválida: {addr}")
        return addr


class ContactoUpdate(BaseModel):
    nombre: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    tipo: Optional[TipoContacto] = None
    recibe_notificaciones: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        addr = v.strip().lower()
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"Dirección de correo inválida: {addr}")
        return addr


class ContactoOut(BaseModel):
    id: int
    cliente_id: int
    nombre: Optional[str] = None
    email: str
    telefono: Optional[str] = None
    tipo: str
    recibe_notificaciones: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Puntero por área (Proyecto → Cliente) ─────────────────────────────────────
# Para el `tipo` dado, este proyecto usa los contactos de `cliente_id` en vez
# de los de sus inversionistas vigentes. Sin fila = usa los inversionistas.

class ProyectoAreaContactoSet(BaseModel):
    cliente_id: int


class ProyectoAreaContactoOut(BaseModel):
    id: int
    proyecto_id: int
    tipo: str
    cliente_id: int
    cliente_nombre: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Servicio Representación ───────────────────────────────────────────────────

class ServicioRepresentacionOut(BaseModel):
    id: int
    proyecto_id: int
    nit_rf: Optional[str] = None
    nombre_rf: Optional[str] = None
    fecha_inicio_representacion: Optional[date] = None
    modalidad_venta: Optional[str] = None
    nombre_comercializador: Optional[str] = None
    codigo_despacho_xm: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


# ── Proyecto principal ────────────────────────────────────────────────────────

class ProyectoCreate(BaseModel):
    nombre_comercial: str
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
    fecha_fin_representacion: Optional[date] = None
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
    p90_mensual_kwh: Optional[list] = None
    p50_mensual_kwh: Optional[list] = None
    p99_mensual_kwh: Optional[list] = None
    codigo_tsf: Optional[str] = None
    srv_operacion: Optional[bool] = None
    srv_representacion: Optional[bool] = None
    srv_cgm: Optional[bool] = None
    srv_ppa: Optional[bool] = None
    srv_promotor: Optional[bool] = None
    srv_rec: Optional[bool] = None
    # Pipeline TSF / próximos a energizarse
    origina_code: Optional[str] = None
    sunfactory_project_id: Optional[int] = None
    fase_construccion: Optional[str] = None
    fecha_estimada_energizacion: Optional[date] = None
    fecha_estimada_editada_manual: Optional[bool] = None
    avance_obra_pct: Optional[float] = None
    mwh_mes_estimado: Optional[float] = None
    origen: Optional[str] = None

    @field_validator("p90_mensual_kwh", "p50_mensual_kwh", "p99_mensual_kwh", mode="before")
    @classmethod
    def coerce_json_list(cls, v):
        import json as _json
        if v is None or isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                result = _json.loads(v)
                return result if isinstance(result, list) else None
            except Exception:
                return None
        return v


class ProyectoUpdate(ProyectoCreate):
    nombre_comercial: Optional[str] = None
    estado: Optional[str] = None


class ProyectoOut(BaseModel):
    id: int
    nombre_comercial: str
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
    fecha_fin_representacion: Optional[date]
    departamento: Optional[str]
    municipio: Optional[str]
    direccion_vereda: Optional[str]
    latitud: Optional[float]
    longitud: Optional[float]
    tipo_conexion: Optional[str]
    operador_red: Optional[str]
    operador_red_legal: Optional[str] = None
    project_id_solenium: Optional[str]
    carpeta_drive_codigo: Optional[str]
    estado_resultados_url: Optional[str]
    income_distribution_method: Optional[str]
    generar_liquidacion: bool
    p90_mensual_kwh: Optional[list] = None
    p50_mensual_kwh: Optional[list] = None
    p99_mensual_kwh: Optional[list] = None
    codigo_tsf: Optional[str] = None
    srv_operacion: bool
    srv_representacion: bool
    srv_cgm: bool
    srv_ppa: bool
    srv_promotor: bool
    srv_rec: bool
    # Pipeline TSF / próximos a energizarse
    origina_code: Optional[str] = None
    sunfactory_project_id: Optional[int] = None
    fase_construccion: Optional[str] = None
    fecha_estimada_energizacion: Optional[date] = None
    fecha_estimada_editada_manual: Optional[bool] = None
    avance_obra_pct: Optional[float] = None
    mwh_mes_estimado: Optional[float] = None
    origen: Optional[str] = None
    servicio_representacion: Optional[ServicioRepresentacionOut] = None
    inversionistas: list[ProyectoInversionistaOut] = []
    info_tecnica: Optional[ProyectoInfoTecnicaOut] = None
    grupos_panel: list[ProyectoGrupoPanelOut] = []
    inversores: list[ProyectoInversorOut] = []
    area_contactos: list[ProyectoAreaContactoOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("inversionistas", "grupos_panel", "inversores", "area_contactos", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            return list(v) if hasattr(v, "__iter__") else [v]
        return v

    @field_validator("p90_mensual_kwh", "p50_mensual_kwh", "p99_mensual_kwh", mode="before")
    @classmethod
    def coerce_json_list(cls, v):
        """Acepta list o JSON-string (datos históricos pre-JSONB)."""
        import json as _json
        if v is None or isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                result = _json.loads(v)
                return result if isinstance(result, list) else None
            except Exception:
                return None
        return v


# ── Proyectos pendientes (Sun Factory + Quoia + Solenium) ──────────────────────

class ProyectoPendienteOut(BaseModel):
    clave: str
    tipo_sugerencia: Literal["crear", "actualizar"]
    confianza: Literal["id", "nombre", "sin_match"]
    fuentes: list[str]
    proyecto_id: Optional[int] = None
    proyecto_nombre_actual: Optional[str] = None
    nombre_sugerido: str
    estado_actual: Optional[str] = None
    estado_sugerido: Optional[str] = None
    fase_construccion_actual: Optional[str] = None
    fase_construccion_sugerida: Optional[str] = None
    tipo_proyecto_sugerido: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    potencia_ac_kw: Optional[float] = None
    capacidad_instalada_kwp: Optional[float] = None
    sub_project: Optional[str] = None
    project_id_solenium: Optional[str] = None
    origina_code: Optional[str] = None
    codigo_tsf: Optional[str] = None
    sunfactory_project_id: Optional[int] = None


class ProyectoPendienteConfirmar(BaseModel):
    """Todos los campos son overrides opcionales -- si no se envían, se usa
    lo que trajo la fuente. `nombre_comercial`/`tipo_proyecto` son
    obligatorios en la práctica para "crear" (el frontend los pre-llena)."""
    nombre_comercial: Optional[str] = None
    tipo_proyecto: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    potencia_ac_kw: Optional[float] = None
    capacidad_instalada_kwp: Optional[float] = None


class ProyectoPendienteIgnorar(BaseModel):
    motivo: Optional[str] = None
