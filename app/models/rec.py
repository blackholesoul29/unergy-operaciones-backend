import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Date, DateTime,
                        ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoRecEnum(str, enum.Enum):
    en_preparacion = "en_preparacion"
    radicado = "radicado"
    en_revision = "en_revision"
    aprobado = "aprobado"
    rechazado = "rechazado"


class RelacionPropietarioEnum(str, enum.Enum):
    propietario = "propietario"
    comprador_ppa = "comprador_ppa"
    tercero = "tercero"


class FuenteDatosEnum(str, enum.Enum):
    asic = "asic"
    medidor = "medidor"
    plataforma_monitoreo = "plataforma_monitoreo"
    otro = "otro"


class RecProceso(Base):
    __tablename__ = "rec_procesos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    codigo_proceso: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoRecEnum, name="estado_rec_enum"), nullable=False, default="en_preparacion")
    fecha_apertura: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_cierre: Mapped[date | None] = mapped_column(Date, nullable=True)
    cantidad_energia_mwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    periodo_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    titular_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    titular_nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    relacion_propietario: Mapped[str | None] = mapped_column(SAEnum(RelacionPropietarioEnum, name="relacion_propietario_enum"), nullable=True)
    tecnologia_generacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fuente_datos: Mapped[str | None] = mapped_column(SAEnum(FuenteDatosEnum, name="fuente_datos_enum"), nullable=True)
    ente_certificador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    numero_radicado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observaciones_ente: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="rec_procesos")
