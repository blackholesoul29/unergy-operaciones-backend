"""Configuración operativa parametrizable por proyecto o global.

Externaliza valores que antes vivían hardcodeados en el estimador de impacto de
fallas (precio de energía de referencia COP/kWh, factor de capacidad solar) hacia
una tabla, permitiendo definirlos por proyecto o de forma global (proyecto_id
NULL). El servicio `app.services.configuracion_service` resuelve el valor
vigente: primero busca una config específica del proyecto y, si no hay, cae a la
global.

Sin `back_populates` para no acoplar `Proyecto` a este módulo nuevo (mismo
criterio que `MantenimientoImpacto.proyecto` / `CumplimientoMensual.proyecto`).
"""
import enum
from datetime import datetime

from sqlalchemy import (BigInteger, String, Boolean, DateTime, Float,
                        ForeignKey, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class TipoParametroConfigEnum(str, enum.Enum):
    PRECIO_ENERGIA = "PRECIO_ENERGIA"
    CAPACIDAD_SOLAR = "CAPACIDAD_SOLAR"


class ConfiguracionOperativa(Base):
    __tablename__ = "configuracion_operativa"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL = configuración global (aplica a cualquier proyecto sin config propia).
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    tipo_parametro: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    valor_float: Mapped[float] = mapped_column(Float, nullable=False)
    unidad: Mapped[str] = mapped_column(String(20), nullable=False)
    fecha_inicio: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true")

    proyecto: Mapped["Proyecto | None"] = relationship("Proyecto")

    __table_args__ = (
        UniqueConstraint(
            "proyecto_id", "tipo_parametro", "fecha_inicio",
            name="uq_config_proyecto_tipo_inicio",
        ),
    )
