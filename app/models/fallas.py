import enum
from datetime import datetime, date, time
from sqlalchemy import (BigInteger, String, Boolean, Date, Time,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class FallaCatCategoria(Base):
    __tablename__ = "fallas_cat_categorias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    icono: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tipos: Mapped[list] = relationship("FallaCatTipo", back_populates="categoria")


class FallaCatTipo(Base):
    __tablename__ = "fallas_cat_tipos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    categoria_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_categorias.id"), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categoria: Mapped["FallaCatCategoria"] = relationship("FallaCatCategoria", back_populates="tipos")
    fallas: Mapped[list] = relationship("Falla", back_populates="tipo")


class FallaCatEstado(Base):
    __tablename__ = "fallas_cat_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    es_estado_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    fallas: Mapped[list] = relationship("Falla", back_populates="estado")
    seguimientos: Mapped[list] = relationship("FallaSeguimiento", back_populates="estado_nuevo")


class FallaCatPrioridad(Base):
    __tablename__ = "fallas_cat_prioridades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    nivel: Mapped[int] = mapped_column(Integer, nullable=False)

    fallas: Mapped[list] = relationship("Falla", back_populates="prioridad")


class FallaCatResolucion(Base):
    __tablename__ = "fallas_cat_resoluciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)

    fallas: Mapped[list] = relationship("Falla", back_populates="resolucion")


class Falla(Base):
    __tablename__ = "fallas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_interno: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    codigo_legado: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    tipo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_tipos.id"), nullable=False)
    estado_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=False)
    prioridad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_prioridades.id"), nullable=False)
    resolucion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_resoluciones.id"), nullable=True)
    registrado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False)
    asignado_a_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_identificacion: Mapped[date] = mapped_column(Date, nullable=False)
    hora_identificacion: Mapped[time | None] = mapped_column(Time, nullable=True)
    fecha_ocurrencia: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_limite_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_cumplido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="fallas")
    tipo: Mapped["FallaCatTipo"] = relationship("FallaCatTipo", back_populates="fallas")
    estado: Mapped["FallaCatEstado"] = relationship("FallaCatEstado", back_populates="fallas")
    prioridad: Mapped["FallaCatPrioridad"] = relationship("FallaCatPrioridad", back_populates="fallas")
    resolucion: Mapped["FallaCatResolucion | None"] = relationship("FallaCatResolucion", back_populates="fallas")
    registrado_por: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[registrado_por_id], back_populates="fallas_registradas")
    asignado_a: Mapped["Usuario | None"] = relationship("Usuario", foreign_keys=[asignado_a_id], back_populates="fallas_asignadas")
    seguimientos: Mapped[list] = relationship("FallaSeguimiento", back_populates="falla")


class FallaSeguimiento(Base):
    __tablename__ = "fallas_seguimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    falla_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado_nuevo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    falla: Mapped["Falla"] = relationship("Falla", back_populates="seguimientos")
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="seguimientos_falla")
    estado_nuevo: Mapped["FallaCatEstado | None"] = relationship("FallaCatEstado", back_populates="seguimientos")
