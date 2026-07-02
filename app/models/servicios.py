import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class FrecuenciaRevisionEnum(str, enum.Enum):
    diaria = "diaria"
    semanal = "semanal"
    mensual = "mensual"


class ModalidadVentaEnum(str, enum.Enum):
    bolsa_directa = "bolsa_directa"
    bolsa_comercializador = "bolsa_comercializador"
    ppa = "ppa"
    interna = "interna"


class ServicioOperacion(Base):
    __tablename__ = "servicio_operacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    plataforma_monitoreo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url_plataforma: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usuario_acceso_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    frecuencia_revision: Mapped[str | None] = mapped_column(SAEnum(FrecuenciaRevisionEnum, name="frecuencia_revision_enum"), nullable=True)
    responsable_operacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disponibilidad_garantizada_pct: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    tarifa_mw_ano_cop: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pct_operacion_ingresos: Mapped[float | None] = mapped_column(Numeric(6, 3), nullable=True)
    sla_critico_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_grave_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_medio_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_leve_descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="servicio_operacion")


class ServicioRepresentacion(Base):
    __tablename__ = "servicio_representacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    nit_rf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nombre_rf: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    modalidad_venta: Mapped[str | None] = mapped_column(SAEnum(ModalidadVentaEnum, name="modalidad_venta_enum"), nullable=True)
    nombre_comercializador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    codigo_despacho_xm: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="servicio_representacion")
