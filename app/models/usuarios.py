import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class RolEnum(str, enum.Enum):
    admin = "admin"
    operaciones = "operaciones"
    monitoreo = "monitoreo"
    liquidaciones = "liquidaciones"
    cgm = "cgm"
    solo_lectura = "solo_lectura"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(SAEnum(RolEnum, name="rol_enum"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    fallas_registradas: Mapped[list] = relationship("Falla", foreign_keys="Falla.registrado_por_id", back_populates="registrado_por")
    fallas_asignadas: Mapped[list] = relationship("Falla", foreign_keys="Falla.asignado_a_id", back_populates="asignado_a")
    seguimientos_falla: Mapped[list] = relationship("FallaSeguimiento", back_populates="usuario")
    mantenimientos: Mapped[list] = relationship("Mantenimiento", back_populates="registrado_por")
    liquidaciones: Mapped[list] = relationship("Liquidacion", back_populates="generado_por")
