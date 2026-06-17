import enum
from datetime import datetime
from sqlalchemy import BigInteger, Integer, String, Boolean, DateTime, Enum as SAEnum, text
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
    coordinador = "coordinador"
    tecnico = "tecnico"


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(SAEnum(RolEnum, name="rol_enum"), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Seguridad: usuarios nuevos (y los migrados desde la contraseña filtrada)
    # deben cambiar su contraseña en el primer acceso.
    force_password_reset: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Versión del esquema de hashing (1 = bcrypt). Permite migrar de algoritmo.
    password_hash_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    fallas_registradas: Mapped[list["Falla"]] = relationship("Falla", foreign_keys="Falla.registrado_por_id", back_populates="registrado_por")
    fallas_asignadas: Mapped[list["Falla"]] = relationship("Falla", foreign_keys="Falla.asignado_a_id", back_populates="asignado_a")
    seguimientos_falla: Mapped[list["FallaSeguimiento"]] = relationship("FallaSeguimiento", back_populates="usuario")
    mantenimientos: Mapped[list["Mantenimiento"]] = relationship("Mantenimiento", back_populates="registrado_por")
    liquidaciones: Mapped[list["Liquidacion"]] = relationship("Liquidacion", back_populates="generado_por")
