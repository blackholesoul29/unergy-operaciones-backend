import enum
import json
from datetime import datetime, date, time
from sqlalchemy import (BigInteger, String, Boolean, Date, Time,
                        DateTime, Integer, Numeric, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.dialects.postgresql import JSONB
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

    tipos: Mapped[list["FallaCatTipo"]] = relationship("FallaCatTipo", back_populates="categoria")


class FallaCatTipo(Base):
    __tablename__ = "fallas_cat_tipos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    categoria_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_categorias.id"), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categoria: Mapped["FallaCatCategoria"] = relationship("FallaCatCategoria", back_populates="tipos")
    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="tipo")


class FallaCatEstado(Base):
    __tablename__ = "fallas_cat_estados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    es_estado_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="estado")
    seguimientos: Mapped[list["FallaSeguimiento"]] = relationship("FallaSeguimiento", back_populates="estado_nuevo")


class FallaCatPrioridad(Base):
    __tablename__ = "fallas_cat_prioridades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    nivel: Mapped[int] = mapped_column(Integer, nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="prioridad")


class FallaCatResolucion(Base):
    __tablename__ = "fallas_cat_resoluciones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)

    fallas: Mapped[list["Falla"]] = relationship("Falla", back_populates="resolucion")


class Falla(Base):
    __tablename__ = "fallas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    codigo_interno: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    codigo_legado: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True, index=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    tipo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_tipos.id"), nullable=True, index=True)
    tipo_libre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    estado_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=False, index=True)
    prioridad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas_cat_prioridades.id"), nullable=False, index=True)
    resolucion_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_resoluciones.id"), nullable=True, index=True)
    registrado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    asignado_a_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True, index=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fecha_identificacion: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hora_identificacion: Mapped[time | None] = mapped_column(Time, nullable=True)
    fecha_ocurrencia: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fecha_resolucion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_limite_horas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_cumplido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fotos_urls: Mapped[str | None] = mapped_column(JSONB, nullable=True)
    centinela: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notificacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    # Feature 2: link to MGS alarm that auto-created this falla
    alarma_monitoreo_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # Feature 4: impact on generation
    kwh_perdidos_estimado: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    impacto_economico_cop: Mapped[float | None] = mapped_column(Numeric(16, 2), nullable=True)
    # Feature 5: documentation
    causa_raiz: Mapped[str | None] = mapped_column(Text, nullable=True)
    acciones_correctivas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Feature 6: programado state — scheduled date for intervention
    fecha_programada: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="fallas")
    tipo: Mapped["FallaCatTipo"] = relationship("FallaCatTipo", back_populates="fallas")
    estado: Mapped["FallaCatEstado"] = relationship("FallaCatEstado", back_populates="fallas")
    prioridad: Mapped["FallaCatPrioridad"] = relationship("FallaCatPrioridad", back_populates="fallas")
    resolucion: Mapped["FallaCatResolucion | None"] = relationship("FallaCatResolucion", back_populates="fallas")
    registrado_por: Mapped["Usuario"] = relationship("Usuario", foreign_keys=[registrado_por_id], back_populates="fallas_registradas")
    asignado_a: Mapped["Usuario | None"] = relationship("Usuario", foreign_keys=[asignado_a_id], back_populates="fallas_asignadas")
    seguimientos: Mapped[list["FallaSeguimiento"]] = relationship("FallaSeguimiento", back_populates="falla")

    @property
    def dias_abierta(self) -> int | None:
        if not self.fecha_identificacion:
            return None
        end = self.fecha_resolucion.date() if self.fecha_resolucion else date.today()
        return max(0, (end - self.fecha_identificacion).days)

    @property
    def sla_limite_dias(self) -> int | None:
        return self.sla_limite_horas // 24 if self.sla_limite_horas else None

    @property
    def tiene_fotos(self) -> bool:
        return bool(self.fotos_urls)

    @property
    def fotos_lista(self) -> list[str]:
        # Con JSONB el ORM ya devuelve list o str según cómo fue almacenado.
        # Manejamos ambos casos + doble-codificación de datos históricos.
        if not self.fotos_urls:
            return []
        if isinstance(self.fotos_urls, list):
            return self.fotos_urls
        # Caso legado: string JSON (antes de la migración a JSONB)
        try:
            result = json.loads(self.fotos_urls)
            if isinstance(result, list):
                return result
            # Doble-codificación histórica → decodificar una vez más
            if isinstance(result, str):
                inner = json.loads(result)
                return inner if isinstance(inner, list) else []
            return []
        except (json.JSONDecodeError, TypeError):
            return []


class FallaSeguimiento(Base):
    __tablename__ = "fallas_seguimientos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    falla_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fallas.id"), nullable=False, index=True)
    usuario_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False, index=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado_nuevo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fallas_cat_estados.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    falla: Mapped["Falla"] = relationship("Falla", back_populates="seguimientos")
    usuario: Mapped["Usuario"] = relationship("Usuario", back_populates="seguimientos_falla")
    estado_nuevo: Mapped["FallaCatEstado | None"] = relationship("FallaCatEstado", back_populates="seguimientos")
