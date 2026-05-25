import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoEquipoEnum(str, enum.Enum):
    medidor_principal = "medidor_principal"
    medidor_respaldo = "medidor_respaldo"
    ct = "ct"
    pt = "pt"
    bornera = "bornera"


class Equipo(Base):
    __tablename__ = "equipos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frontera_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fronteras.id"), nullable=False, index=True)
    tipo_equipo: Mapped[str] = mapped_column(SAEnum(TipoEquipoEnum, name="tipo_equipo_enum"), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modelo_referencia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clase_exactitud: Mapped[str | None] = mapped_column(String(20), nullable=True)
    num_elementos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_instalacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_ultima_calibracion: Mapped[date | None] = mapped_column(Date, nullable=True)
    laboratorio_onac: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_vencimiento_calibracion: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Solo medidores
    requiere_medidor_respaldo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    marca_modem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modelo_modem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    protocolo_comunicacion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    apn_sim_operador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    frontera: Mapped["Frontera"] = relationship("Frontera", back_populates="equipos")
    sellos: Mapped[list] = relationship("EquipoSello", back_populates="equipo")


class EquipoSello(Base):
    __tablename__ = "equipos_sellos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    equipo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("equipos.id"), nullable=False, index=True)
    numero_sello: Mapped[str] = mapped_column(String(100), nullable=False)
    fecha_instalacion: Mapped[date] = mapped_column(Date, nullable=False)
    persona_instalo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retirado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fecha_retiro: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo_retiro: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    equipo: Mapped["Equipo"] = relationship("Equipo", back_populates="sellos")
