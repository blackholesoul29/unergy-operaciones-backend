from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class InformeGuardado(Base):
    __tablename__ = "informes_guardados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20))           # "op" | "fmo" | "port"
    sub_project: Mapped[str] = mapped_column(String(200))   # proyecto/portfolio key
    periodo_desde: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    periodo_hasta: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    periodo_display: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proyecto_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)

    html_content: Mapped[str] = mapped_column(Text)
    charts_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON str

    estado: Mapped[str] = mapped_column(String(20), default="borrador")
    # estados: borrador → revisado → aprobado

    creado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    editado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    aprobado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    creado_por_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    editado_por_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aprobado_por_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    editado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correo_enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    correo_enviado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
