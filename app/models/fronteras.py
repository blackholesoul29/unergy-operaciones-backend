import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text,
                        Index, CheckConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base
from app.models.contrato_frontera import ContratoFrontera


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


class EstadoOperacionalEnum(str, enum.Enum):
    activo = "activo"
    inactivo = "inactivo"
    en_registro = "en_registro"
    descomisionado = "descomisionado"


class FuenteLecturaEnum(str, enum.Enum):
    medidor_principal = "medidor_principal"
    medidor_respaldo = "medidor_respaldo"


class Frontera(Base):
    __tablename__ = "fronteras"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    frontera_gemela_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fronteras.id"), nullable=True, index=True)
    agrupada_bajo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fronteras.id"), nullable=True, index=True)
    embebida_bajo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("fronteras.id"), nullable=True, index=True)

    codigo_frontera: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    nombre_frontera: Mapped[str] = mapped_column(String(255), nullable=False)
    codigo_propio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo_frontera: Mapped[str] = mapped_column(SAEnum(TipoFronteraEnum, name="tipo_frontera_enum"), nullable=False)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoFronteraEnum, name="estado_frontera_enum"), nullable=False, default="en_registro")
    fecha_registro_asic: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_primer_registro_asic: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Clasificación técnica
    tipo_punto_medicion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nivel_tension_kv: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    punto_conexion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capacidad_transporte_mw: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    capacidad_transporte_compartida_mw: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    capacidad_efectiva_mw: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    factor_perdidas: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    clase_ct: Mapped[str | None] = mapped_column(String(20), nullable=True)
    clase_pt: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Ubicación
    municipio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    centro_poblado: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subestacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    latitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    altitud_msnm: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Registro ASIC
    registrada_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nivel_tension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transferencia_maxima_kwh: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    representante_frontera: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    operador_red: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operador_red_zona: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Vínculo estructurado hacia el catálogo de operadores (operador_red arriba
    # sigue siendo el texto de GESCON; este FK es para la integración del
    # reporte CGM -- ver operadores_red_contactos para los correos).
    operador_red_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("operadores_red.id"), nullable=True, index=True)
    nombre_cgm: Mapped[str | None] = mapped_column(String(255), nullable=True)
    predio_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nombre_predio: Mapped[str | None] = mapped_column(String(255), nullable=True)
    representante_ddv: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Agentes
    nit_rf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    nit_cgm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    representante_anterior: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agente_exportador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agente_importador: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nombre_recurso_generacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clasificacion_recurso: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Datos operativos
    consumo_promedio_mensual_mwh: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    relacion_transformacion_ct: Mapped[str | None] = mapped_column(String(100), nullable=True)
    relacion_transformacion_pt: Mapped[str | None] = mapped_column(String(100), nullable=True)
    niu: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Códigos SIC
    codigo_sic_ddv: Mapped[str | None] = mapped_column(String(50), nullable=True)
    codigo_sic_submercado_exportador: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_sic_submercado_consumo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_sic_submercado_usuario: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Medidor principal
    nro_serie_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    marca_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    modelo_med_ppal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clase_medidor: Mapped[str | None] = mapped_column(String(50), nullable=True)
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

    # Agrupación/embebido
    es_agrupadora: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    factor_psf: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    es_principal_embebido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    factor_acordado: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    factor_ajuste: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    factor_perdidas_frontera_principal: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Quoia meter link
    quoia_meter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Id interno del border en Quoia -- lo requiere get_border_report_status(),
    # que no acepta frt_code. Se guarda al confirmar desde /quoia/pendientes
    # para no tener que resolverlo con una llamada extra en cada reporte CGM.
    quoia_border_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Estado operacional (lifecycle)
    estado_operacional: Mapped[str | None] = mapped_column(
        SAEnum(EstadoOperacionalEnum, name="estado_operacional_enum"),
        nullable=True, default="activo",
    )

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Clasificación industrial
    codigo_ciiu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    clasificacion_industrial_general: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clasificacion_industrial_especifica: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tipo_tecnologia: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Códigos SIC adicionales
    codigo_sic_frontera_generacion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    potencia_maxima_declarada: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    codigo_sic_frontera_usuario: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="fronteras")
    lecturas: Mapped[list["FronteraLectura"]] = relationship("FronteraLectura", back_populates="frontera")
    xm_datos: Mapped[list["LiquidacionXMDato"]] = relationship("LiquidacionXMDato", back_populates="frontera")
    operador: Mapped["OperadorRed | None"] = relationship("OperadorRed", back_populates="fronteras")
    contratos: Mapped[list["ContratoServicio"]] = relationship(
        "ContratoServicio", secondary=ContratoFrontera.__tablename__, back_populates="fronteras",
    )


class FronteraLectura(Base):
    __tablename__ = "fronteras_lecturas"
    __table_args__ = (
        Index("ix_frontera_lectura_frontera_fecha", "frontera_id", "fecha_hora"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frontera_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fronteras.id"), nullable=False, index=True)
    fuente: Mapped[str] = mapped_column(SAEnum(FuenteLecturaEnum, name="fuente_lectura_enum"), nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    periodo_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fin: Mapped[date] = mapped_column(Date, nullable=False)
    energia_activa_import_kwh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_activa_export_kwh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_react_ind_import_kvarh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_react_ind_export_kvarh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_react_cap_import_kvarh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    energia_react_cap_export_kvarh: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    frontera: Mapped["Frontera"] = relationship("Frontera", back_populates="lecturas")


class FronteraQuoiaIgnorada(Base):
    """Borders de Quoia marcados a propósito como 'no aplica' en el panel de
    /fronteras/quoia/pendientes, para que dejen de aparecer como pendientes
    (ej. medidores de prueba, borders de un tercero)."""

    __tablename__ = "fronteras_quoia_ignoradas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    frt_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    motivo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ignorado_por_usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
