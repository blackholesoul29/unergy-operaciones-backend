import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text,
                        CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class TipoFronteraEnum(str, enum.Enum):
    generacion = "generacion"
    consumo = "consumo"
    generacion_consumo = "generacion_consumo"
    consumo_auxiliar = "consumo_auxiliar"
    consumo_propio = "consumo_propio"


class EstadoFronteraEnum(str, enum.Enum):
    activa = "activa"
    en_registro = "en_registro"
    cancelada = "cancelada"
    en_falla = "en_falla"


# Clases de precision de metrologia (CREG, fronteras comerciales) -- acotadas
# a los valores que de verdad se usan hoy (auditoria de integridad de
# Fronteras, 2026-08-25), no al catalogo completo de la norma.
class ClaseCtEnum(str, enum.Enum):
    clase_0_2 = "0.2"
    clase_0_2s = "0.2s"
    clase_0_5s = "0.5s"


class ClasePtEnum(str, enum.Enum):
    clase_0_2 = "0.2"
    clase_0_5 = "0.5"


class ClaseMedidorEnum(str, enum.Enum):
    clase_0_2s = "0.2s"
    clase_0_5s = "0.5s"


# Estos tres enum guardan el VALOR en Postgres ("0.5s"), no el nombre del miembro
# ("clase_0_5s"): así están creados los tipos y así están las 94 filas. SQLAlchemy
# usa el nombre salvo que se le diga lo contrario, y al leer reventaba con
#     LookupError: '0.5s' is not among the defined enum values
# tumbando con 500 cualquier consulta que cargara fronteras -- incluida la lista de
# proyectos, que las trae con selectinload.
def _por_valor(enum_cls):
    return [m.value for m in enum_cls]


class Frontera(Base):
    __tablename__ = "fronteras"
    __table_args__ = (
        CheckConstraint("transferencia_maxima_kwh IS NULL OR transferencia_maxima_kwh >= 0", name="ck_fronteras_transferencia_maxima_kwh_no_negativa"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)

    # unique=True se reemplazó por un índice único parcial case-insensitive
    # (ver migración 077) -- una fila borrada libera su código para que otra
    # pueda reusarlo, y dos códigos que solo difieren en mayúsculas ya no
    # pueden coexistir como fronteras activas distintas.
    codigo_frontera: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nombre_frontera: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo_frontera: Mapped[str] = mapped_column(SAEnum(TipoFronteraEnum, name="tipo_frontera_enum"), nullable=False)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoFronteraEnum, name="estado_frontera_enum"), nullable=False, default="en_registro")
    fecha_registro_asic: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Clasificación técnica
    tipo_punto_medicion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nivel_tension_kv: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    clase_ct: Mapped[str | None] = mapped_column(SAEnum(ClaseCtEnum, name="clase_ct_enum", values_callable=_por_valor), nullable=True)
    clase_pt: Mapped[str | None] = mapped_column(SAEnum(ClasePtEnum, name="clase_pt_enum", values_callable=_por_valor), nullable=True)

    # Registro ASIC
    nivel_tension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transferencia_maxima_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    fecha_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Vínculo estructurado hacia el catálogo de operadores -- para la
    # integración del reporte CGM, ver operadores_red_contactos para los correos.
    operador_red_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operadores_red.id"), nullable=True, index=True)

    # Agentes
    agente_exportador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agente_importador: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Códigos SIC
    codigo_sic_submercado_exportador: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_sic_submercado_consumo: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Medidor principal
    nro_serie_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marca_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    modelo_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clase_medidor: Mapped[str | None] = mapped_column(SAEnum(ClaseMedidorEnum, name="clase_medidor_enum", values_callable=_por_valor), nullable=True)
    num_elementos_med_ppal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_cambio_med_ppal: Mapped[date | None] = mapped_column(Date, nullable=True)
    entidad_calibradora_med_ppal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_calibracion_med_ppal: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_actualizacion_ppal: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Medidor respaldo
    nro_serie_med_resp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marca_med_resp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    modelo_med_resp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    num_elementos_med_resp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fecha_cambio_med_resp: Mapped[date | None] = mapped_column(Date, nullable=True)
    entidad_calibradora_med_resp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_calibracion_med_resp: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_actualizacion_resp: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Id interno del border en Quoia -- lo requiere get_border_report_status(),
    # que no acepta frt_code. Se guarda al confirmar desde /quoia/pendientes,
    # pensado originalmente para no tener que resolverlo con una llamada
    # extra en cada reporte CGM -- pero HOY resolver_borders() (reporte_cgm.py)
    # nunca lo lee: sigue resolviendo en vivo contra el catálogo completo de
    # Quoia por frt_code (curvas.obtener_borders_crudos(), cacheado 30 min).
    # Solo 45/145 fronteras activas lo tienen poblado (auditoría CGM
    # 2026-08-26, finding #6) -- usarlo como fast-path necesitaría antes un
    # backfill de las que faltan.
    quoia_border_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="fronteras")
    operador: Mapped["OperadorRed | None"] = relationship("OperadorRed", back_populates="fronteras")
    contratos: Mapped[list["ContratoServicio"]] = relationship(
        "ContratoServicio", secondary="contrato_frontera", back_populates="fronteras",
    )


class FronteraQuoiaIgnorada(Base):
    """Borders de Quoia marcados a propósito como 'no aplica' en el panel de
    /fronteras/quoia/pendientes, para que dejen de aparecer como pendientes
    (ej. medidores de prueba, borders de un tercero)."""

    __tablename__ = "fronteras_quoia_ignoradas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frt_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    ignorado_por_usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
