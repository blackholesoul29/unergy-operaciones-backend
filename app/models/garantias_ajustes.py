"""GarantiaAjuste — registro de ajustes XM semanales/TXR/mensuales."""
import enum
from datetime import date
from typing import Any, Optional

from sqlalchemy import BigInteger, Date, Enum as SAEnum, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TipoAjusteEnum(str, enum.Enum):
    semanal = "semanal"
    txr     = "txr"
    mensual = "mensual"


class GarantiaAjuste(Base, TimestampMixin):
    __tablename__ = "garantias_ajustes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tipo: Mapped[TipoAjusteEnum] = mapped_column(
        SAEnum(TipoAjusteEnum, name="tipo_ajuste_xm_enum"), nullable=False
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    pb:            Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    restricciones: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    stn:           Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    trm:           Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    ptb:           Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    total_ungc:          Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    total_ungg:          Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    total_consignar:     Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    disponible_custodia: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    congelado:           Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    saldo:               Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    total_ajuste_txr:    Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)

    # Snapshot completo de la hoja madre (bloques, panel, precios) para re-renderizar.
    snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
