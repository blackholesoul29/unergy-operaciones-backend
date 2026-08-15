"""Modelos del módulo "Retos Q": tablero trimestral de retos del equipo.

Tres tablas: el trimestre (rango de fechas editable), sus métricas y el valor
semanal de cada métrica. **Las semanas no se persisten**: se derivan del rango
del trimestre (app/services/retos.py::generar_semanas), y los valores quedan
anclados al LUNES de su semana. Si se mueve el rango del Q, los valores que
quedan fuera simplemente no se muestran; no se borran.

`tipo_agregacion`, `direccion` y `estado` se guardan como String y se validan en
la capa de API/schemas — mismo criterio de registros_cnd: evita el baile de
ALTER TYPE de los enums de PostgreSQL.

Las tres tablas son nuevas y las crea Base.metadata.create_all en el arranque;
no se altera ninguna tabla existente (no se toca _PENDING_DDLS).
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RetoTrimestre(Base):
    """Un trimestre del tablero (Q1..Q4 de un año), con su rango editable."""

    __tablename__ = "retos_trimestre"
    __table_args__ = (
        UniqueConstraint("anio", "trimestre", name="uq_retos_trimestre_anio_q"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trimestre: Mapped[int] = mapped_column(Integer, nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(160), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    metricas: Mapped[list["RetoMetrica"]] = relationship(
        "RetoMetrica", back_populates="reto", cascade="all, delete-orphan",
        order_by="RetoMetrica.orden, RetoMetrica.id",
    )


class RetoMetrica(Base):
    """Métrica de un trimestre: se llena una vez por semana."""

    __tablename__ = "retos_metrica"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("retos_trimestre.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    unidad: Mapped[str | None] = mapped_column(String(40), nullable=True)
    meta: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    # suma | promedio | ultimo | maximo
    tipo_agregacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suma", server_default="suma"
    )
    # mayor_mejor | menor_mejor
    direccion: Mapped[str] = mapped_column(
        String(20), nullable=False, default="mayor_mejor", server_default="mayor_mejor"
    )
    decimales: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    responsable: Mapped[str | None] = mapped_column(String(120), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    reto: Mapped["RetoTrimestre"] = relationship("RetoTrimestre", back_populates="metricas")
    valores: Mapped[list["RetoValorSemanal"]] = relationship(
        "RetoValorSemanal", back_populates="metrica", cascade="all, delete-orphan",
        order_by="RetoValorSemanal.semana_inicio",
    )


class RetoValorSemanal(Base):
    """Valor de una métrica para una semana concreta (clave = lunes)."""

    __tablename__ = "retos_valor_semanal"
    __table_args__ = (
        UniqueConstraint("metrica_id", "semana_inicio", name="uq_retos_valor_metrica_semana"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metrica_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("retos_metrica.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Siempre el LUNES de la semana.
    semana_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    valor: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    actualizado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    metrica: Mapped["RetoMetrica"] = relationship("RetoMetrica", back_populates="valores")
    actualizado_por: Mapped["Usuario | None"] = relationship("Usuario")  # noqa: F821
