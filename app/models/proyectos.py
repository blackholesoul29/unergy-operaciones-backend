import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, String, Numeric, Boolean, Date,
                        DateTime, Integer, ForeignKey, Enum as SAEnum, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ClasificacionRegulatoriaEnum(str, enum.Enum):
    AGP = "AGP"
    AGPE = "AGPE"
    AGGE = "AGGE"
    GD = "GD"
    DER = "DER"
    otra = "otra"


class TipoTecnologiaEnum(str, enum.Enum):
    solar = "solar"
    eolica = "eolica"
    hidraulica = "hidraulica"
    biomasa = "biomasa"
    otra = "otra"


class EstadoProyectoEnum(str, enum.Enum):
    en_desarrollo = "en_desarrollo"
    en_operacion = "en_operacion"
    suspendido = "suspendido"
    cancelado = "cancelado"


class TipoProyectoEnum(str, enum.Enum):
    minigranja = "minigranja"
    autoconsumo = "autoconsumo"
    gd = "gd"
    movilidad_electrica = "movilidad_electrica"
    otro = "otro"


class TipoInversorEnum(str, enum.Enum):
    string = "string"
    central = "central"
    microinversor = "microinversor"
    hibrido = "hibrido"
    otro = "otro"


class Portafolio(Base):
    __tablename__ = "portafolios"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyectos: Mapped[list["Proyecto"]] = relationship("Proyecto", back_populates="portafolio")


class Proyecto(Base):
    __tablename__ = "proyectos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=True)
    portafolio_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("portafolios.id"), nullable=True)
    proyecto_padre_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True)

    nombre_comercial: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_bitacora: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nombre_clientes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    topic_slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    sub_project: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)

    clasificacion_regulatoria: Mapped[str | None] = mapped_column(SAEnum(ClasificacionRegulatoriaEnum, name="clasificacion_regulatoria_enum"), nullable=True)
    tipo_tecnologia: Mapped[str | None] = mapped_column(SAEnum(TipoTecnologiaEnum, name="tipo_tecnologia_enum"), nullable=True)
    tipo_proyecto: Mapped[str | None] = mapped_column(SAEnum(TipoProyectoEnum, name="tipo_proyecto_enum"), nullable=True)

    potencia_instalada_kwp: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    potencia_con_cen_mw: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    cantidad_total_paneles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    produccion_especifica_kwh_kwp: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    codigo_cnd: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estado: Mapped[str] = mapped_column(SAEnum(EstadoProyectoEnum, name="estado_proyecto_enum"), nullable=False, default="en_desarrollo")
    fecha_entrada_operacion: Mapped[date | None] = mapped_column(Date, nullable=True)

    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    municipio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    direccion_vereda: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitud: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    tipo_conexion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    operador_red: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id_solenium: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    # Servicios activos
    srv_operacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    srv_representacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    srv_cgm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    srv_ppa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    srv_promotor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    srv_rec: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Monitoreo
    alias_monitoreo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # P50/P90 monthly simulation (JSON arrays of 12 kWh values, index 0 = enero)
    p90_mensual_kwh: Mapped[str | None] = mapped_column(Text, nullable=True)
    p50_mensual_kwh: Mapped[str | None] = mapped_column(Text, nullable=True)
    codigo_tsf: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Liquidación
    carpeta_drive_codigo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    estado_resultados_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    income_distribution_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generar_liquidacion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    cliente: Mapped["Cliente | None"] = relationship("Cliente", back_populates="proyectos")
    portafolio: Mapped["Portafolio | None"] = relationship("Portafolio", back_populates="proyectos")
    subproyectos: Mapped[list] = relationship("Proyecto", foreign_keys=[proyecto_padre_id], uselist=True)
    info_tecnica: Mapped["ProyectoInfoTecnica | None"] = relationship("ProyectoInfoTecnica", back_populates="proyecto", uselist=False)
    grupos_panel: Mapped[list] = relationship("ProyectoGrupoPanel", back_populates="proyecto", uselist=True)
    inversores: Mapped[list] = relationship("ProyectoInversor", back_populates="proyecto", uselist=True)
    contactos: Mapped[list] = relationship("ProyectoContacto", back_populates="proyecto", uselist=True)
    inversionistas: Mapped[list] = relationship("ProyectoInversionista", back_populates="proyecto", uselist=True)
    fronteras: Mapped[list] = relationship("Frontera", back_populates="proyecto", uselist=True)
    fallas: Mapped[list] = relationship("Falla", back_populates="proyecto", uselist=True)
    generaciones: Mapped[list] = relationship("GeneracionDiaria", back_populates="proyecto", uselist=True)
    mantenimientos: Mapped[list] = relationship("Mantenimiento", back_populates="proyecto", uselist=True)
    liquidaciones: Mapped[list] = relationship("Liquidacion", back_populates="proyecto", uselist=True)
    contratos_arriendo: Mapped[list] = relationship("ContratoArriendo", back_populates="proyecto", uselist=True)
    asic_solicitudes: Mapped[list] = relationship("AsicSolicitud", back_populates="proyecto", uselist=True)
    rec_procesos: Mapped[list] = relationship("RecProceso", back_populates="proyecto", uselist=True)
    promotor_seguimientos: Mapped[list] = relationship("PromoterSeguimiento", back_populates="proyecto", uselist=True)
    contratos_servicio: Mapped[list] = relationship("ContratoServicio", back_populates="proyecto", uselist=True)
    ppa_contratos: Mapped[list] = relationship("PPAContrato", secondary="ppa_contrato_proyectos", uselist=True, viewonly=True)
    kpis: Mapped[list] = relationship("OperacionKPI", back_populates="proyecto", uselist=True)
    servicio_operacion: Mapped["ServicioOperacion | None"] = relationship("ServicioOperacion", back_populates="proyecto", uselist=False)
    servicio_representacion: Mapped["ServicioRepresentacion | None"] = relationship("ServicioRepresentacion", back_populates="proyecto", uselist=False)
    servicio_cgm: Mapped["ServicioCGM | None"] = relationship("ServicioCGM", back_populates="proyecto", uselist=False)


class ProyectoInfoTecnica(Base):
    __tablename__ = "proyecto_info_tecnica"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), unique=True, nullable=False)
    cantidad_total_paneles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tiene_almacenamiento: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    capacidad_almacenamiento_kwh: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    marca_almacenamiento: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modelo_almacenamiento: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="info_tecnica")


class ProyectoGrupoPanel(Base):
    __tablename__ = "proyecto_grupos_panel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    potencia_pico_wp: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    cantidad: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="grupos_panel")


class ProyectoInversor(Base):
    __tablename__ = "proyecto_inversores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modelo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    potencia_nominal_kw: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    numero_serie: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str | None] = mapped_column(SAEnum(TipoInversorEnum, name="tipo_inversor_enum"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="inversores")


class ProyectoContacto(Base):
    __tablename__ = "proyecto_contactos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recibe_notificaciones: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="contactos")


class ProyectoInversionista(Base):
    __tablename__ = "proyecto_inversionistas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=False)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False)
    contrato_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    porcentaje_participacion: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    es_patrimonio_autonomo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fecha_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto", back_populates="inversionistas")
    cliente: Mapped["Cliente"] = relationship("Cliente", back_populates="participaciones")

    @property
    def cliente_nombre(self) -> str:
        return self.cliente.razon_social_nombre if self.cliente else ""
