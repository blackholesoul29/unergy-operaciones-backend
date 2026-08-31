import enum
from datetime import datetime, date
from sqlalchemy import (BigInteger, Integer, String, Boolean, Date, DateTime,
                        ForeignKey, Enum as SAEnum, Numeric, Text, Table, Column)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoComercialEnum(str, enum.Enum):
    """Pipeline de 6 etapas. Desde 2026-08-02 vive en la OFERTA, no en el cliente:
    una oferta se envía, se acepta y se firma por su cuenta, sin arrastrar a sus
    hermanas del mismo cliente (Tecni-plast tiene Margaritas 1 firmada y
    Margaritas 2 todavía en envío).

    Vocabulario actual y de dónde viene cada valor:
      oportunidad ← prospeccion
      oferta      ← envio_oferta (que en 2026-07-15 venía de 'oferta'; vuelve al original)
      contrato    ← negociacion_contrato
      firmado, operando (← servicio_operativo ← 'fin'), declinado
      terminado   nuevo: el suministro llegó a su fecha_fin
    El tipo PostgreSQL sigue llamándose estado_oportunidad_enum: renombrarlo no
    aporta nada y sí agrega un modo de falla en el arranque.
    """

    oportunidad = "oportunidad"
    oferta = "oferta"
    contrato = "contrato"
    firmado = "firmado"
    operando = "operando"
    # El contrato corrió y se venció. No se mueve a mano: lo pone el job diario
    # cuando pasa la fecha_fin del PPA (ver cerrar_contratos_vencidos).
    terminado = "terminado"
    declinado = "declinado"


# Alias de compatibilidad: el nombre viejo siguió importándose en varios módulos.
EstadoOportunidadEnum = EstadoComercialEnum


class TipoOfertaComercialEnum(str, enum.Enum):
    """Tipo de sub-oferta dentro de una oportunidad-cliente."""
    servicios_operacionales = "servicios_operacionales"
    compra_energia = "compra_energia"
    comunidad_energetica = "comunidad_energetica"


class ResultadoOfertaEnum(str, enum.Enum):
    pendiente = "pendiente"
    aceptado = "aceptado"
    declinado = "declinado"


class TipoGestionEnum(str, enum.Enum):
    llamada = "llamada"
    correo = "correo"
    reunion = "reunion"
    whatsapp = "whatsapp"
    nota = "nota"


class Oportunidad(Base):
    """Unidad del pipeline comercial. Etapa PREVIA al flujo de operación:
    apunta al Cliente existente y agrupa proyectos/oferta/contratos de UN
    negocio. Un cliente puede tener varias oportunidades en el tiempo."""

    __tablename__ = "oportunidades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("clientes.id"), nullable=False, index=True)
    # Etiqueta del negocio; si NULL la UI muestra la razón social del cliente.
    nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # DEPRECADO (2026-08-02): el estado del pipeline se mudó a la oferta. La
    # columna sigue aquí porque borrarla rompería los históricos y no aporta
    # nada; la API ya no la lee, deriva el estado del cliente de sus ofertas
    # (la más avanzada). No escribir aquí sin actualizar también las ofertas.
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoComercialEnum, name="estado_oportunidad_enum"),
        nullable=False, default="oportunidad")
    estado_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Consecutivo manual por ahora (automatización = futuro explícito).
    numero_oferta: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fecha_tentativa_inicio_representacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_tentativa_inicio_compra_energia: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Manual por ahora (cálculo automático = futuro explícito).
    fecha_estimada_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True solo para las creadas por el backfill de clientes históricos.
    es_migrada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    creado_por_usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cliente: Mapped["Cliente"] = relationship("Cliente")
    gestiones: Mapped[list["OportunidadGestion"]] = relationship(
        "OportunidadGestion", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="desc(OportunidadGestion.fecha)")
    historial: Mapped[list["OportunidadEstadoHistorial"]] = relationship(
        "OportunidadEstadoHistorial", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="desc(OportunidadEstadoHistorial.created_at)")
    documentos: Mapped[list["ClienteDocumentoComercial"]] = relationship(
        "ClienteDocumentoComercial",
        primaryjoin="ClienteDocumentoComercial.oportunidad_id == Oportunidad.id",
        foreign_keys="ClienteDocumentoComercial.oportunidad_id", uselist=True, viewonly=True)
    ofertas: Mapped[list["OportunidadOferta"]] = relationship(
        "OportunidadOferta", back_populates="oportunidad",
        cascade="all, delete-orphan", order_by="OportunidadOferta.id")


class OportunidadEstadoHistorial(Base):
    """Una fila por transición de estado (y una al crear, con anterior=NULL).

    Desde 2026-08-02 las transiciones son de la OFERTA: `oferta_id` dice cuál.
    Las filas viejas lo traen NULL — son del tiempo en que el estado era del
    cliente — y se conservan como histórico.
    """

    __tablename__ = "oportunidad_estado_historial"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    oferta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("oportunidad_ofertas.id", ondelete="CASCADE"), nullable=True, index=True)
    estado_anterior: Mapped[str | None] = mapped_column(String(20), nullable=True)
    estado_nuevo: Mapped[str] = mapped_column(String(20), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="historial")


class OportunidadGestion(Base):
    """Bitácora comercial (llamada/correo/reunión/whatsapp/nota). Registrar
    una gestión reinicia el contador de la alerta de N días sin respuesta."""

    __tablename__ = "oportunidad_gestiones"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    # A CUÁL oferta se refiere la gestión (2026-08-19). NULL = gestión del
    # cliente, que cuenta para todas sus ofertas — así se comportaban todas
    # antes, y las filas viejas lo conservan. Con la etapa viviendo en la oferta
    # desde 2026-08-02, una gestión sin dueño apagaba la alerta de las hermanas:
    # llamar por Margaritas 1 dejaba de avisar que Margaritas 2 seguía muda.
    # SET NULL al borrar la oferta: la conversación pasó, el registro queda.
    oferta_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("oportunidad_ofertas.id", ondelete="SET NULL"),
        nullable=True, index=True)
    # Fix 2026-08-19: "tipo_gestion_enum" ya era el nombre del tipo de
    # GestionRegistro (app/models/gestion.py, migración 007 -- pqr/preventivo/
    # correctivo). Como esta tabla nunca tuvo su propia migración (solo
    # create_all() al arrancar), reusaba ese tipo existente en vez de crear
    # el suyo -- cualquier insert con llamada/correo/reunion/whatsapp/nota
    # violaba el enum, asi que oportunidad_gestiones nunca guardo una fila.
    tipo: Mapped[str] = mapped_column(SAEnum(TipoGestionEnum, name="tipo_gestion_oportunidad_enum"), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    # Editable: permite registrar hoy una llamada que fue ayer.
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuarios.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="gestiones")


# Plantas de una OFERTA (muchos-a-muchos, 2026-08-18). Existe porque una oferta
# puede cubrir varias plantas ("Balmora 1 y 2", "GD ISABELA 1 y GD ISABELA 2"), y
# con el `proyecto_id` único había que elegir una: el PPA mostraba la generación de
# esa planta como si fuera la del contrato entero.
#
# NO reemplaza a `oportunidad_ofertas.proyecto_id`, que lo leen el vinculador, la
# ficha operativa y proyectos_operando. Es aditiva: si la oferta tiene filas acá se
# usan, y si no se cae a la columna vieja. Al firmar, estas plantas son las que
# pasan a `ppa_contrato_proyectos`.
oportunidad_oferta_proyectos_table = Table(
    "oportunidad_oferta_proyectos",
    Base.metadata,
    Column("oferta_id", BigInteger, ForeignKey("oportunidad_ofertas.id", ondelete="CASCADE"), primary_key=True),
    Column("proyecto_id", BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), primary_key=True),
)


class OportunidadOferta(Base):
    """Sub-oferta = una planta × un tipo de servicio dentro de la oportunidad-cliente.
    Cada fila de las hojas de prospección (Servicios / Energía / Comunidad) es una
    de estas. La oportunidad es del cliente; sus ofertas cuelgan aquí con su propio
    consecutivo, precio y resultado (aceptado/declinado)."""

    __tablename__ = "oportunidad_ofertas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    oportunidad_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("oportunidades.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(SAEnum(TipoOfertaComercialEnum, name="tipo_oferta_comercial_enum"), nullable=False)
    planta_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proyecto_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    numero_oferta: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    precio_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Etapa del pipeline DE ESTA OFERTA (2026-08-02). Fuente única de la verdad.
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoComercialEnum, name="estado_oportunidad_enum"),
        nullable=False, default="oportunidad", server_default="oportunidad")
    # Entrada a la etapa actual — base del contador de días sin respuesta.
    estado_desde: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    # DERIVADO de `estado` (ver estado_a_resultado). Se conserva porque lo leen
    # el import de hojas y las vistas viejas; nunca se edita a mano.
    resultado: Mapped[str] = mapped_column(
        SAEnum(ResultadoOfertaEnum, name="resultado_oferta_enum"),
        nullable=False, default="pendiente", server_default="pendiente")
    etapa_texto: Mapped[str | None] = mapped_column(String(60), nullable=True)
    fecha_oferta: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_tentativa_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Fin tentativo del suministro (2026-08-18). Con el inicio ya existente, es lo
    # que permite que un PPA en BORRADOR declare su periodo y su duración antes de
    # firmarse. Tentativa a propósito: cuando se firma, el periodo pactado vive en
    # ppa_contratos y esta columna deja de leerse.
    fecha_fin_tentativa: Mapped[date | None] = mapped_column(Date, nullable=True)
    contrato_firmado: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # Detalle crudo de la hoja de origen: para servicios_operacionales incluye
    # {servicios: [...], servicios_texto, fpo}; extensible por tipo de oferta.
    detalle: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Envío de la oferta (2026-07-28). fecha_oferta (arriba) es el PRIMER envío;
    # aquí van los toques posteriores y la respuesta del cliente. Que
    # fecha_ultima_respuesta sea NULL significa que el cliente NUNCA respondió,
    # que es la señal fuerte del tablero (Los Apóstoles: 6 toques, 0 respuestas).
    seguimientos: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fecha_ultima_respuesta: Mapped[date | None] = mapped_column(Date, nullable=True)
    documento_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # ── En qué contrato desembocó la oferta (2026-08-02) ─────────────────────
    # Una oferta evoluciona en un contrato: compra de energía → PPA, servicios
    # → contrato de representación/O&M. Las condiciones comerciales (periodo,
    # tarifa, indexación, energía contratada, carpeta de soporte) NO se copian
    # aquí: ya viven en ppa_contratos / contratos_servicio, que es lo que leen
    # Cumplimiento y Liquidaciones. Duplicarlas garantizaría que se desincronicen.
    ppa_contrato_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id", ondelete="SET NULL"), nullable=True, index=True)
    contrato_servicio_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contratos_servicio.id", ondelete="SET NULL"), nullable=True, index=True)
    # ── Ficha operativa declarada (2026-08-03) ───────────────────────────────
    # Lo que el equipo consulta por API vive en `proyectos`, pero la mayoría de
    # las ofertas del pipeline no tienen proyecto todavía (la planta no existe).
    # Estas columnas son el fallback declarado; la API resuelve por cascada
    # Proyecto → oferta → null y dice de dónde salió cada dato (ficha_operativa).
    municipio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Solo el FK al catálogo, sin texto libre: `proyectos.operador_red` (texto)
    # ya está declarado legacy en su propio modelo y no se repite el error. Si
    # falta un operador, se arregla el catálogo.
    operador_red_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("operadores_red.id"), nullable=True, index=True)
    # Generación mensual ESTIMADA, en kWh para hablar el idioma del CRM
    # (cantidad_minima_kwh_mes). No confundir con esa: aquella es un compromiso
    # contractual del PPA, esta es una estimación técnica de la planta.
    energia_promedio_kwh_mes: Mapped[float | None] = mapped_column(
        Numeric(14, 3), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    oportunidad: Mapped["Oportunidad"] = relationship("Oportunidad", back_populates="ofertas")
