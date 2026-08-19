import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, ForeignKey, Enum as SAEnum, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoContactoEnum(str, enum.Enum):
    operacional = "operacional"
    cgm = "cgm"
    liquidacion = "liquidacion"
    comercial = "comercial"
    contable = "contable"


class Contacto(Base):
    """Contacto de notificación de un Cliente, por área (`tipo`). Los correos
    reales viven siempre aquí -- un Proyecto nunca guarda un correo suelto,
    solo puede apuntar (ver ProyectoAreaContacto) a qué Cliente usar por área."""

    __tablename__ = "contactos"
    __table_args__ = (
        UniqueConstraint("cliente_id", "email", "tipo", name="uq_contacto_cliente_email_tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoContactoEnum, name="tipo_contacto_enum"), nullable=False)
    # server_default (no solo default=True a nivel Python) -- sin esto, un
    # INSERT que no pase por el ORM (ej. el backfill de la migración 037)
    # viola NOT NULL, porque el default de SQLAlchemy solo se aplica cuando
    # el propio ORM construye el INSERT. Ver alembic/versions/037_contactos_unificados.py.
    recibe_notificaciones: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="contactos")


class ProyectoAreaContacto(Base):
    """Puntero por área: para el `tipo` dado, este Proyecto usa los contactos
    del Cliente indicado en vez de los de sus inversionistas vigentes. Sin
    fila para un tipo = usa los inversionistas. Ver app/services/contactos.py."""

    __tablename__ = "proyecto_area_contacto"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "tipo", name="uq_proyecto_area_contacto_tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoContactoEnum, name="tipo_contacto_enum"), nullable=False)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="area_contactos")
    cliente: Mapped["Cliente"] = relationship("Cliente")
