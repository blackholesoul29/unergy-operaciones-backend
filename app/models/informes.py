import enum
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoInformeEnum(str, enum.Enum):
    op = "op"
    fmo = "fmo"
    port = "port"
    ranking = "ranking"


class EstadoInformeEnum(str, enum.Enum):
    borrador = "borrador"
    revisado = "revisado"
    aprobado = "aprobado"
    fallido = "fallido"   # generación automática falló (datos insuficientes / error)


class InformeGuardado(Base):
    __tablename__ = "informes_guardados"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoInformeEnum, name="tipo_informe_enum"))
    sub_project: Mapped[str] = mapped_column(String(200))   # proyecto/portfolio key
    periodo_desde: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    periodo_hasta: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    periodo_display: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proyecto_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)

    html_content: Mapped[str] = mapped_column(Text)
    charts_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    estado: Mapped[str] = mapped_column(SAEnum(EstadoInformeEnum, name="estado_informe_enum"), default="borrador")

    creado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    editado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    aprobado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True
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

    # Pipeline de verificación: lista de comentarios del revisor (Juan José).
    # Cada item: {id, autor_email, autor_nombre, mensaje, created_at,
    #             resuelto, resuelto_en, resuelto_por_email, resuelto_por_nombre,
    #             respuesta}
    comentarios: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # Sólo informes de portafolio (tipo='port'): lista ordenada de miembros.
    # Cada item: {sub_project, nombre, orden, html_inline}
    #   - html_inline se usa SOLO si el proyecto no tiene informe individual ('op')
    #     guardado para el mismo período; si lo tiene, la sección se compone en vivo
    #     desde ese individual y html_inline queda en null.
    miembros: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    enviado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    enviado_por_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
