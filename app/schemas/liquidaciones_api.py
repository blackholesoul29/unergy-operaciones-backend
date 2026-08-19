from typing import Optional

from pydantic import BaseModel


class ProyectoLiquidacionesOut(BaseModel):
    """Proyecto de esta base cruzado con su configuración en la API de Liquidaciones."""

    proyecto_id: int
    nombre_comercial: str
    tipo_proyecto: Optional[str] = None
    estado: Optional[str] = None
    # Identificador del proyecto en la API externa (proyectos.sub_project).
    nombre_topico: Optional[str] = None
    # True si el tópico existe en la API; si es False los campos vienen vacíos.
    en_api: bool = False

    sic_gen: Optional[str] = None
    sic_con: Optional[str] = None
    frt_gen: Optional[str] = None
    frt_con: Optional[str] = None
    ac_power: Optional[float] = None
    from_generator: Optional[bool] = None
    from_commercializer: Optional[bool] = None


class ProyectoLiquidacionesUpdate(BaseModel):
    """Campos editables de la configuración de liquidaciones (§3.1 de la guía)."""

    sic_gen: Optional[str] = None
    sic_con: Optional[str] = None
    frt_gen: Optional[str] = None
    frt_con: Optional[str] = None
    ac_power: Optional[float] = None
    from_generator: Optional[bool] = None
    from_commercializer: Optional[bool] = None
