from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class OperadorRed(Base):
    __tablename__ = "operadores_red"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre_legal: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    nombre_comercial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    contactos: Mapped[list["OperadorRedContacto"]] = relationship(
        "OperadorRedContacto", back_populates="operador", cascade="all, delete-orphan"
    )
    fronteras: Mapped[list["Frontera"]] = relationship("Frontera", back_populates="operador")
    proyectos: Mapped[list["Proyecto"]] = relationship("Proyecto", back_populates="operador")


class OperadorRedContacto(Base):
    __tablename__ = "operadores_red_contactos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    operador_red_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("operadores_red.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    operador: Mapped["OperadorRed"] = relationship("OperadorRed", back_populates="contactos")
