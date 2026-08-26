import enum
from datetime import datetime, date
from typing import List
from sqlalchemy import (
    BigInteger, String, Numeric, Boolean, Date, DateTime, Integer,
    ForeignKey, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, deferred
from sqlalchemy.sql import func
from app.models.base import Base


class TipoPanelEnum(str, enum.Enum):
    preliquidacion = "preliquidacion"
    oficial = "oficial"


class GrupoLineaEnum(str, enum.Enum):
    ingresos = "ingresos"
    comercializacion = "comercializacion"
    costos = "costos"
    facturas = "facturas"
    resultado = "resultado"


class PanelContable(Base):
    """
    Borrador contable de un proyecto para un período. Cada panel es el resultado
    de cargar un Estado de Resultados (ER) y dividirlo por inversionista.
    'preliquidacion' = estimado; 'oficial' = real. Se comparan después.
    """
    __tablename__ = "panel_contable"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", "tipo", name="uq_panel_proyecto_periodo_tipo"),
        Index("ix_panel_periodo_tipo", "periodo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="preliquidacion")

    # Liquidación de ingresos y de costos son independientes; cada una consume su
    # propia cadena de consecutivos. (liquidar se mantiene por compatibilidad.)
    liquidar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    liquidar_ingresos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    liquidar_costos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generar_mandatos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tiene_bolsa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tiene_costos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ingreso_bruto_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    comercializador: Mapped[str | None] = mapped_column(String(120), nullable=True)

    fecha_firma: Mapped[date | None] = mapped_column(Date, nullable=True)
    consecutivo_ingresos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutivo_costos: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # De dónde salieron los ingresos y la comercialización de este panel:
    # 'er' = del Excel del Estado de Resultados (NEU, Nitro y todo lo anterior a
    # la migración), 'api' = de income_statement_data. Las líneas de costos ya
    # traen su propia `fuente`, pero los ingresos no tenían ninguna marca y sin
    # esto no había forma de saber con qué se armó un panel.
    origen: Mapped[str] = mapped_column(String(10), nullable=False, default="er",
                                        server_default="er")

    er_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Snapshot del ER recalculado: {hoja: {coord: valor}} en JSON. Permite releer
    # una celda al cambiar el mapeo sin volver a subir el archivo. deferred: es un
    # TEXT grande que no se necesita al listar/serializar paneles; se carga solo
    # cuando se accede (mapeo-celda / fuente-ingreso), no en cada GET /panel-contable.
    er_snapshot: Mapped[str | None] = deferred(mapped_column(Text, nullable=True))
    generado_por_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lineas: Mapped[List["PanelContableLinea"]] = relationship(
        "PanelContableLinea", back_populates="panel",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class TipoLiquidacionEnum(str, enum.Enum):
    normal = "normal"
    neu = "neu"
    nitro = "nitro"


class ClasificacionLiquidacion(Base):
    """
    Tipo de liquidación de un proyecto PARA UN PERÍODO concreto. Un proyecto
    puede ser NEU en enero y normal en marzo, por eso la clave es
    (proyecto_id, periodo). Sin registro → se asume 'normal'.

    El tipo determina cómo se parsea la sección de ingresos del ER:
      - normal: ingreso bruto venta de energía
      - neu:    despacho + ventas/compras bolsa + distribución superávit + ajuste
      - nitro:  ingreso bruto + ventas/compras bolsa + comercialización
    """
    __tablename__ = "clasificacion_liquidacion"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", name="uq_clasif_proyecto_periodo"),
        Index("ix_clasif_periodo", "periodo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    tipo: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PanelContableLinea(Base):
    """
    Una línea del detalle contable de un panel, ya dividida por inversionista.
    grupo: ingresos | comercializacion | costos | facturas | resultado
    """
    __tablename__ = "panel_contable_linea"
    __table_args__ = (
        Index("ix_panel_linea_panel", "panel_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("panel_contable.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proyecto_inversionista_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyecto_inversionistas.id", ondelete="SET NULL"), nullable=True
    )
    inversionista_nombre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    porcentaje: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)

    grupo: Mapped[str] = mapped_column(String(20), nullable=False)
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    valor_cop: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    comprobante_contable: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Celda del ER de donde salió el valor base (ej. hoja="Sheet1", celda="H35").
    # La comparten todas las líneas del mismo concepto (el origen es del 100%).
    hoja: Mapped[str | None] = mapped_column(String(120), nullable=True)
    celda: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Origen del valor cuando NO viene del ER sino de un módulo: 'om' | 'arriendos'.
    # NULL = valor del ER (lo normal). El frontend lo muestra como etiqueta.
    fuente: Mapped[str | None] = mapped_column(String(20), nullable=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    panel: Mapped["PanelContable"] = relationship("PanelContable", back_populates="lineas")


class MapeoCeldaConcepto(Base):
    """
    Mapeo persistente por (proyecto, concepto) → celda del ER (hoja!celda) que la
    usuaria confirmó. Si existe, el parser lee ESA celda directamente en vez de
    proponer por etiqueta, así el próximo mes ya sale bien solo.
    """
    __tablename__ = "mapeo_celda_concepto"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "concepto", name="uq_mapeo_proyecto_concepto"),
        Index("ix_mapeo_proyecto", "proyecto_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    hoja: Mapped[str] = mapped_column(String(120), nullable=False)
    celda: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AliasFuenteIngreso(Base):
    """
    Nombre que la usuaria le puso a una fuente de ingreso, anclado a la celda del
    ER de donde sale (columna_origen, ej. "Sheet1!G35"). Un proyecto puede tener
    varias fuentes (Terpel 1, Terpel 2, Bolsa, PPA…). Como la celda casi no cambia
    de un mes al otro, al recordar (columna_origen → etiqueta) el parser propone el
    mismo nombre el mes siguiente y resucita fuentes manuales que la usuaria agregó.
    """
    __tablename__ = "alias_fuente_ingreso"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "columna_origen", name="uq_alias_proyecto_columna"),
        Index("ix_alias_proyecto", "proyecto_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    columna_origen: Mapped[str] = mapped_column(String(40), nullable=False)  # "Sheet1!G35"
    etiqueta: Mapped[str] = mapped_column(String(255), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PanelSoporte(Base):
    """
    Soporte/comprobante (archivo en Drive) de una transacción del panel, anclado a
    (proyecto, periodo, tipo, grupo, concepto) — NO a la línea, porque las líneas se
    borran y recrean al recargar el ER. Así el soporte sobrevive a recargas. El
    concepto es del 100% (la transacción), no del inversionista.
    """
    __tablename__ = "panel_soporte"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", "tipo", "grupo", "concepto",
                         name="uq_panel_soporte"),
        Index("ix_panel_soporte_lookup", "proyecto_id", "periodo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)   # "YYYY-MM"
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)     # preliquidacion | oficial
    grupo: Mapped[str] = mapped_column(String(20), nullable=False)
    concepto: Mapped[str] = mapped_column(String(255), nullable=False)
    archivo_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    archivo_nombre: Mapped[str | None] = mapped_column(String(300), nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PanelConsecutivo(Base):
    """El consecutivo contable de UN inversionista en un panel.

    En el negocio el consecutivo es por partícipe, no por proyecto: Uruaco en
    julio de 2026 lleva 1185, 1186 y 1187 de ingresos para sus tres
    inversionistas, con 1246, 1247 y 1248 de costos. `PanelContable` tiene un
    solo par de campos, que sirve para los proyectos de un único inversionista
    pero pierde los demás; de ahí esta tabla.

    Vive aparte de `PanelContableLinea` a propósito: las líneas se borran y se
    regeneran cada vez que se rearma el panel, y el consecutivo tiene que
    sobrevivir a eso -- por la misma razón por la que ya vivía en el panel.

    La clave es la identidad de negocio (proyecto, período, tipo, inversionista)
    y no el `panel_id`, para que tampoco se pierda si el panel se borra y se
    vuelve a crear.
    """
    __tablename__ = "panel_consecutivo"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "periodo", "tipo", "inversionista_nombre",
                         name="uq_panel_consec_proy_per_tipo_inv"),
        Index("ix_panel_consec_periodo_tipo", "periodo", "tipo"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    periodo: Mapped[str] = mapped_column(String(7), nullable=False)   # "YYYY-MM"
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)     # preliquidacion | oficial
    # Se guarda el nombre y no solo el id porque el id puede quedar en NULL
    # (proyectos sin inversionista cargado) y en Postgres un UNIQUE con NULL
    # admite duplicados, que es justo lo que hay que evitar aquí.
    proyecto_inversionista_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyecto_inversionistas.id", ondelete="SET NULL"), nullable=True
    )
    inversionista_nombre: Mapped[str] = mapped_column(String(255), nullable=False)

    consecutivo_ingresos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutivo_costos: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
