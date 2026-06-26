from datetime import datetime
from decimal import Decimal
from sqlalchemy import (BigInteger, String, Numeric, DateTime,
                        ForeignKey, UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class XMGeneracionHistorico(Base):
    """Histórico de generación reportada por XM (SinergoX), ingerido desde Excel.

    A diferencia de `generacion_diaria` (datos de Solenium / inversores), esta tabla
    guarda la generación oficial de XM por medidor (frontera) y fecha de medición,
    habilitando análisis de series temporales independientes de la fuente Solenium.

    La clave única (proyecto_id, measurement_date, meter_id) permite upserts
    idempotentes: reprocesar el mismo archivo no duplica registros.
    """
    __tablename__ = "xm_generation_history"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "measurement_date", "meter_id",
                         name="uq_xm_gen_hist_proj_date_meter"),
        Index("ix_xm_gen_hist_proj_date", "proyecto_id", "measurement_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False)
    meter_id: Mapped[str] = mapped_column(String(100), nullable=False)
    measurement_date: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    # kWh es la unidad canónica del repo para generación cruda (ver mem_ingestion_service,
    # generacion.kwh_real, fronteras.energia_*_kwh). El servicio de ingesta convierte a kWh
    # cuando el Excel viene rotulado en MWh.
    generation_kwh: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")  # noqa: F821
