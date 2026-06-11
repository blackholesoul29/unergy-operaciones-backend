from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class GarantiaAjusteCreate(BaseModel):
    tipo:  Literal["semanal", "txr", "mensual"]
    fecha: date

    pb:            Optional[float] = None
    restricciones: Optional[float] = None
    stn:           Optional[float] = None
    trm:           Optional[float] = None
    ptb:           Optional[float] = None

    total_ungc:          Optional[float] = None
    total_ungg:          Optional[float] = None
    total_consignar:     Optional[float] = None

    disponible_custodia: Optional[float] = None
    congelado:           Optional[float] = None
    saldo:               Optional[float] = None

    total_ajuste_txr:    Optional[float] = None


class GarantiaAjusteUpdate(BaseModel):
    fecha: Optional[date] = None

    pb:            Optional[float] = None
    restricciones: Optional[float] = None
    stn:           Optional[float] = None
    trm:           Optional[float] = None
    ptb:           Optional[float] = None

    total_ungc:          Optional[float] = None
    total_ungg:          Optional[float] = None
    total_consignar:     Optional[float] = None

    disponible_custodia: Optional[float] = None
    congelado:           Optional[float] = None
    saldo:               Optional[float] = None

    total_ajuste_txr:    Optional[float] = None


class GarantiaAjusteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id:    int
    tipo:  str
    fecha: date

    pb:            Optional[float] = None
    restricciones: Optional[float] = None
    stn:           Optional[float] = None
    trm:           Optional[float] = None
    ptb:           Optional[float] = None

    total_ungc:          Optional[float] = None
    total_ungg:          Optional[float] = None
    total_consignar:     Optional[float] = None

    disponible_custodia: Optional[float] = None
    congelado:           Optional[float] = None
    saldo:               Optional[float] = None

    total_ajuste_txr:    Optional[float] = None

    created_at: datetime
    updated_at: datetime
