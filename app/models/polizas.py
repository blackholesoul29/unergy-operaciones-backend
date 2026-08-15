# unergy-operaciones-backend/app/models/polizas.py
from datetime import datetime, date
from sqlalchemy import BigInteger, String, Numeric, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class Poliza(Base):
    __tablename__ = "polizas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False, index=True)

    # Póliza
    numero_poliza: Mapped[str | None] = mapped_column(String(100), nullable=True)
    poliza_om: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    valor_poliza: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Presupuesto (insumos editables)
    mano_obra: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    estructura: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    paneles: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    inversores: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    otros: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Auto-calculado y persistido al guardar — ver calcular_derivados() en
    # app/api/v1/polizas.py. Nunca se edita a mano directamente.
    valor_total_proyecto: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    link_estudio_suelos: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Indexación IPP (insumos editables, para auditar lucro cesante)
    ipp_base: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    ipp_base_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    ipp_provisional: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    ipp_provisional_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    tarifa_base: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    generacion_anual_p90_kwh: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    # Auto-calculado y persistido al guardar (tarifa_base × %indexación ×
    # generacion_anual_p90_kwh) — ver calcular_derivados().
    valor_lucro_cesante: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
