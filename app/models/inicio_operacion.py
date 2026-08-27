from datetime import datetime, date
from sqlalchemy import BigInteger, String, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ProyectoInicioOperacion(Base):
    """Ficha de inicio de operación de un proyecto.

    La vista que la editaba se retiró del frontend (2026-08-21); se conserva
    como fuente de lectura de app/api/v1/informe_om.py (fecha_energizacion,
    fecha_inicio_operacion, empresa_contratista, pendientes, y checklist para
    derivar 4 semáforos). `pruebas`/`documentos` se eliminaron 2026-08-27 por
    no tener ningún lector.
    """
    __tablename__ = "proyecto_inicio_operacion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=False, unique=True, index=True
    )

    empresa_contratista: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_energizacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicio_operacion: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Sección 1 — checklist de sistemas: { item_key: 'aprobado'|'rechazado'|'na' }
    checklist = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Sección 5 — pendientes: [ { descripcion, responsable, fecha_compromiso, clasificacion, estado, observaciones } ]
    pendientes = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
