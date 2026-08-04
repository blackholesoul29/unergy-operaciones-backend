"""Resultado diario del pipeline de reporte de energía (Quoia · Solenium ·
ASIC) por frontera -- una fila por (frontera_id, fecha).

Sin tablas de histórico aparte: la mediana/forma horaria usada por el factor
de pérdida y el relleno horario se calcula consultando estas mismas tablas
(ver app/services/reporte_energia/historial.py) -- 'curva_final' y 'caso' ya
contienen todo lo necesario, no hace falta duplicar en un CSV/tabla extra
como en el pipeline original (Reporte-Energia).
"""
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    BigInteger, String, Numeric, Boolean, Date, DateTime, Integer,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class ReporteEnergiaGeneracion(Base):
    """Un día de reporte para una frontera de Generación.

    'caso' es el árbol de decisión 0-8 de clasificador.py (0 = frontera de
    terceros, 1 = CGM válido, 2/3/4 = medidor/inversores según corrija el
    error, 5 = sin inversores, 6 = apagado, 7 = crudos/reconectador
    completos, 8 = crudos parciales) -- o -1 si el clasificador lanzó una
    excepción para esta frontera ese día (ver orquestador._marcar_error_generacion).
    """
    __tablename__ = "reporte_energia_generacion"
    __table_args__ = (
        UniqueConstraint("frontera_id", "fecha", name="uq_reporte_energia_gen_frontera_fecha"),
        Index("ix_reporte_energia_gen_fecha", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frontera_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fronteras.id", ondelete="CASCADE"), nullable=False, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    caso: Mapped[int] = mapped_column(Integer, nullable=False)
    medidor_usado: Mapped[str | None] = mapped_column(String(30), nullable=True)
    energia_final_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    curva_final: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 24 floats o null

    fp: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    fp_calculada: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    error_final_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    energia_cgm_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    estado_reporte: Mapped[str | None] = mapped_column(String(20), nullable=True)
    energia_solenium_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    solenium_completo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nota_solenium: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Totales crudos del medidor de nodo (independientes de qué Caso ganó ese
    # día) -- necesarios para el factor de pérdida histórico (E_med/E_inv),
    # que se calcula sobre TODOS los días con medidor completo, no solo los
    # que terminaron en un Caso basado en medidor (ver historial.py).
    energia_medidor_principal_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_medidor_respaldo_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    medidor_principal_completo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    medidor_respaldo_completo: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    horas_rellenadas_reconectador: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    horas_rellenadas_solenium: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    horas_rellenadas_historico: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recuperacion_datos: Mapped[str | None] = mapped_column(String(255), nullable=True)

    revisar_manualmente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    editado_manualmente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validado_por_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    validado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Mensaje de la excepción cuando caso=-1 (clasificador falló para esta
    # frontera+fecha) -- null en cualquier otro caso.
    error_clasificacion: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Resultado del último intento de envío a Quoia/ASIC (POST /enviar) --
    # null si nunca se ha intentado enviar esta frontera+fecha.
    enviado_quoia_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enviado_quoia_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enviado_quoia_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    frontera: Mapped["Frontera"] = relationship("Frontera")
    validado_por: Mapped["Usuario | None"] = relationship("Usuario")


class ReporteEnergiaExclusion(Base):
    """Ventana de fechas en la que una frontera (Generación o Consumo) no se
    clasifica en absoluto -- para casos como un CT en falla ya reportado a
    XM, donde no se quiere reportar ningún número automático mientras se
    resuelve. Alcance mínimo a propósito (una especie de bandera con
    trazabilidad): quién, por qué, desde/hasta cuándo -- no depende de
    Fallas (ese módulo requiere monitoreo/representación, que no todas las
    fronteras tienen; CGM y representación son servicios separados).

    Real: GD Agustín 2, frontera_id=98, CT en falla reportado a XM
    (2026-08-04).
    """
    __tablename__ = "reporte_energia_exclusiones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frontera_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fronteras.id", ondelete="CASCADE"), nullable=False, index=True)
    motivo: Mapped[str] = mapped_column(String(500), nullable=False)
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin_estimada: Mapped[date | None] = mapped_column(Date, nullable=True)
    creado_por_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=False)
    resuelta_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    frontera: Mapped["Frontera"] = relationship("Frontera")
    creado_por: Mapped["Usuario"] = relationship("Usuario")


class ReporteEnergiaConsumo(Base):
    """Un día de reporte para una frontera de Consumo.

    'caso' es texto ('CGM' / 'Medidor' / 'Histórico' / 'Sin dato') -- árbol
    de clasificador_consumo.py, más corto que el de generación porque no hay
    inversores contra qué validar cruzado -- o 'Error' si el clasificador
    lanzó una excepción para esta frontera ese día.
    """
    __tablename__ = "reporte_energia_consumo"
    __table_args__ = (
        UniqueConstraint("frontera_id", "fecha", name="uq_reporte_energia_con_frontera_fecha"),
        Index("ix_reporte_energia_con_fecha", "fecha"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frontera_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fronteras.id", ondelete="CASCADE"), nullable=False, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)

    caso: Mapped[str] = mapped_column(String(20), nullable=False)
    medidor_usado: Mapped[str | None] = mapped_column(String(30), nullable=True)
    energia_final_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    curva_final: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    energia_cgm_kwh: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    estado_reporte: Mapped[str | None] = mapped_column(String(20), nullable=True)

    horas_rellenadas_historico: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recuperacion_datos: Mapped[str | None] = mapped_column(String(255), nullable=True)

    revisar_manualmente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    editado_manualmente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validado_por_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    validado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_clasificacion: Mapped[str | None] = mapped_column(String(500), nullable=True)

    enviado_quoia_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enviado_quoia_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enviado_quoia_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    frontera: Mapped["Frontera"] = relationship("Frontera")
    validado_por: Mapped["Usuario | None"] = relationship("Usuario")
