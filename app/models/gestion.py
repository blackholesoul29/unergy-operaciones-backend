import enum
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoGestionEnum(str, enum.Enum):
    pqr = "pqr"
    preventivo = "preventivo"
    correctivo = "correctivo"


class GestionRegistro(Base):
    __tablename__ = "gestion_registros"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[str] = mapped_column(SAEnum(TipoGestionEnum, name="tipo_gestion_enum"), nullable=False)
    titulo: Mapped[str] = mapped_column(String(500), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")  # type: ignore[name-defined]
