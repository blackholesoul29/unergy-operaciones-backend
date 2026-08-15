"""Schemas del módulo "Retos Q" (contrato secciones 4 y 5).

Nota sobre `tipo_agregacion` / `direccion` en los cuerpos de entrada: van como
`str` y NO como `Literal`, porque el contrato exige responder **400** cuando el
valor no es válido y un `Literal` de Pydantic produciría 422. La validación se
hace en el router (`app/api/v1/retos.py::_validar_catalogos`) contra las
constantes de `app/services/retos.py`.
"""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

TipoAgregacionLiteral = Literal["suma", "promedio", "ultimo", "maximo"]
DireccionLiteral = Literal["mayor_mejor", "menor_mejor"]
EstadoMetricaLiteral = Literal["sin_datos", "en_riesgo", "atencion", "cumple", "excede"]
EstadoPeriodoLiteral = Literal["proximo", "en_curso", "cerrado"]


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------

class RetoUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


class MetricaCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    unidad: Optional[str] = None
    meta: Optional[float] = None
    tipo_agregacion: str = "suma"
    direccion: str = "mayor_mejor"
    decimales: int = 0
    responsable: Optional[str] = None
    orden: Optional[int] = None


class MetricaUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    unidad: Optional[str] = None
    meta: Optional[float] = None
    tipo_agregacion: Optional[str] = None
    direccion: Optional[str] = None
    decimales: Optional[int] = None
    responsable: Optional[str] = None
    orden: Optional[int] = None
    activa: Optional[bool] = None


class ValorSemanalIn(BaseModel):
    valor: Optional[float] = None
    nota: Optional[str] = None


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------

class SeriePunto(BaseModel):
    semana: int
    valor: Optional[float] = None


class MetricaResumen(BaseModel):
    id: int
    reto_id: int
    nombre: str
    descripcion: Optional[str] = None
    unidad: Optional[str] = None
    meta: Optional[float] = None
    tipo_agregacion: str
    direccion: str
    decimales: int
    responsable: Optional[str] = None
    orden: int
    activa: bool
    consolidado: Optional[float] = None
    meta_esperada: Optional[float] = None
    avance_pct: Optional[float] = None
    cumplimiento_pct: Optional[float] = None
    estado: EstadoMetricaLiteral
    semanas_con_dato: int
    serie: list[SeriePunto] = []

    model_config = {"from_attributes": True}


class RetoResumen(BaseModel):
    id: int
    anio: int
    trimestre: int
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    fecha_inicio: date
    fecha_fin: date
    total_semanas: int
    semana_actual: Optional[int] = None
    estado_periodo: EstadoPeriodoLiteral
    total_metricas: int
    semanas_con_datos: int
    avance_global_pct: Optional[float] = None
    metricas: list[MetricaResumen] = []

    model_config = {"from_attributes": True}


class SemanaOut(BaseModel):
    numero: int
    inicio: date
    fin: date
    inicio_efectivo: date
    fin_efectivo: date
    etiqueta: str
    rango_label: str
    es_actual: bool
    es_futura: bool
    parcial: bool

    model_config = {"from_attributes": True}


class ValorCelda(BaseModel):
    valor: Optional[float] = None
    nota: Optional[str] = None
    actualizado_por: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RetoDetalle(RetoResumen):
    semanas: list[SemanaOut] = []
    # {str(metrica_id): {str(semana_inicio ISO): ValorCelda}}
    valores: dict[str, dict[str, ValorCelda]] = {}


class RetosAnioOut(BaseModel):
    anio: int
    anios_disponibles: list[int] = []
    retos: list[RetoResumen] = []
