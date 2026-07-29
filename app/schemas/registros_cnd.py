"""Schemas Pydantic v2 de la seccion "Registros CND/ASIC".

Los resumenes ("en que va el proyecto") se devuelven como dict desde el servicio;
aqui se tipan las entradas (Create/Update/In) y las salidas de CRUD simple
(equipos, documentos, parametros 9.3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
class RegistroConexionCreate(BaseModel):
    proyecto_id: int
    numero_expediente: Optional[str] = None
    id_requerimiento_or: Optional[str] = None
    numero_solicitud_appweb: Optional[str] = None
    fecha_conexion_estimada: Optional[date] = None
    vigencia_aprobacion_conexion: Optional[date] = None
    fecha_visita_protecciones: Optional[date] = None
    tipo_visita_protecciones: Optional[str] = None
    exporta: bool = False
    comercializador_es_or: bool = False
    punto_conexion_texto: Optional[str] = None
    notas: Optional[str] = None


class RegistroConexionUpdate(BaseModel):
    numero_expediente: Optional[str] = None
    id_requerimiento_or: Optional[str] = None
    numero_solicitud_appweb: Optional[str] = None
    fecha_conexion_estimada: Optional[date] = None
    vigencia_aprobacion_conexion: Optional[date] = None
    fecha_visita_protecciones: Optional[date] = None
    tipo_visita_protecciones: Optional[str] = None
    exporta: Optional[bool] = None
    comercializador_es_or: Optional[bool] = None
    punto_conexion_texto: Optional[str] = None
    notas: Optional[str] = None


class TransicionIn(BaseModel):
    etapa: str
    a_estado: str
    nota: Optional[str] = None
    actor: Optional[str] = None


# ---------------------------------------------------------------------------
# Parametros 9.3
# ---------------------------------------------------------------------------
class Parametros93In(BaseModel):
    numero_unidades_equivalentes: Optional[int] = None
    potencia_nominal_inversor_ac_mw: Optional[float] = None
    minimo_tecnico_mw: Optional[float] = None
    arranque_autonomo: Optional[bool] = None
    acuerdo_conexion_compartida: Optional[bool] = None
    voltaje_max_kv: Optional[float] = None
    voltaje_nominal_kv: Optional[float] = None
    voltaje_min_kv: Optional[float] = None
    frecuencia_max_hz: Optional[float] = None
    frecuencia_min_hz: Optional[float] = None
    impedancia_equivalente_ohm: Optional[float] = None
    icc_subtrans_pico_kap: Optional[float] = None
    icc_subtrans_3f_ka: Optional[float] = None
    icc_subtrans_2f_ka: Optional[float] = None
    icc_subtrans_1f_ka: Optional[float] = None
    icc_estado_estable_ka: Optional[float] = None
    in_eq_ka: Optional[float] = None
    coef_derrateo_altura: Optional[str] = None
    notas: Optional[str] = None


class Parametros93Out(Parametros93In):
    id: int
    registro_id: int
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Equipos de frontera
# ---------------------------------------------------------------------------
class EquipoCreate(BaseModel):
    tipo: str
    marca: Optional[str] = None
    modelo: Optional[str] = None
    serial: Optional[str] = None
    fecha_solicitud_solenium: Optional[date] = None
    fecha_envio_quoia: Optional[date] = None
    fecha_parametrizacion: Optional[date] = None
    fecha_envio_or: Optional[date] = None
    fecha_vencimiento_calibracion: Optional[date] = None


class EquipoUpdate(BaseModel):
    tipo: Optional[str] = None
    marca: Optional[str] = None
    modelo: Optional[str] = None
    serial: Optional[str] = None
    fecha_solicitud_solenium: Optional[date] = None
    fecha_envio_quoia: Optional[date] = None
    fecha_parametrizacion: Optional[date] = None
    fecha_envio_or: Optional[date] = None
    fecha_vencimiento_calibracion: Optional[date] = None


class EquipoOut(EquipoCreate):
    id: int
    registro_id: int
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
class DocumentoCreate(BaseModel):
    tipo: str
    radicado: Optional[str] = None
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    firmado_por: Optional[str] = None
    url_drive: Optional[str] = None
    estado: str = "BORRADOR"


class DocumentoUpdate(BaseModel):
    tipo: Optional[str] = None
    radicado: Optional[str] = None
    fecha_emision: Optional[date] = None
    fecha_vencimiento: Optional[date] = None
    firmado_por: Optional[str] = None
    url_drive: Optional[str] = None
    estado: Optional[str] = None


class DocumentoOut(DocumentoCreate):
    id: int
    registro_id: int
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ProyectoDisponibleOut(BaseModel):
    id: int
    nombre_comercial: str
    codigo_cnd: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
