"""Modelos de la seccion "Registros": expediente documental de un proyecto.

Tres tablas, ancladas al Proyecto y no a un flujo de estados:

  documentos_proyecto          una casilla del expediente (proceso + numeral)
  documentos_proyecto_archivo  los archivos montados en esa casilla
  parametros_proyecto          el valor de cada dato, UNA sola vez

Por que es distinto de registro_conexion / registro_documento (el modulo
registros_cnd que ya existe): aquel modela el TRAMITE -- etapas, transiciones,
hitos, alertas, y sus documentos son evidencia de una etapa. Este modela el
EXPEDIENTE -- que papeles tiene el proyecto y que dice cada uno. Un proyecto
tiene expediente desde que existe, sin importar en que etapa del tramite va.
Ver decision D-01: se dejan convivir en vez de fusionarlos.

El principio del modulo: un dato, una fila. Si la serie del medidor aparece en
la hoja de vida, en el acta, en el certificado de calibracion y en las fotos,
sigue siendo UNA fila de parametros_proyecto. Los documentos que la contienen se
saben por catalogo (services/registros_proyecto/mapa_documentos.py), no
repitiendo el dato.
"""

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String,
    Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class EstadoDocumento:
    """Estado de carga de una casilla. No es un flujo de aprobacion."""

    PENDIENTE = "PENDIENTE"     # todavia no se monta nada
    CARGADO = "CARGADO"         # tiene al menos un archivo
    NO_APLICA = "NO_APLICA"     # el item no aplica a este proyecto

    TODOS = (PENDIENTE, CARGADO, NO_APLICA)


class OrigenArchivo:
    LINK = "LINK"       # url pegada a mano (Drive, SharePoint, lo que sea)
    DRIVE = "DRIVE"     # subido por la plataforma al Drive de la empresa

    TODOS = (LINK, DRIVE)


class DocumentoProyecto(Base):
    """Una casilla del expediente: (proyecto, proceso, numeral del item).

    Se crea de forma perezosa: la fila aparece cuando el usuario toca el item
    por primera vez. La lista completa de items que DEBERIAN existir vive en el
    catalogo, no en la base -- asi agregar un item nuevo al proceso no obliga a
    sembrar filas en todos los proyectos.
    """

    __tablename__ = "documentos_proyecto"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "proceso", "item_codigo",
                         name="uq_documentos_proyecto_item"),
        Index("ix_documentos_proyecto_proyecto_proceso", "proyecto_id", "proceso"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    proceso: Mapped[str] = mapped_column(String(10), nullable=False)      # SIC | CND
    item_codigo: Mapped[str] = mapped_column(String(10), nullable=False)  # "01".."28" | "9.1".."9.10"

    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=EstadoDocumento.PENDIENTE)

    # Datos del tramite que son del documento en si, no del proyecto: cada carta
    # del proceso CND trae su propio radicado y su propia fecha. Ver D-14.
    radicado: Mapped[str | None] = mapped_column(String(120), nullable=True)
    fecha_emision: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date, nullable=True)
    emisor: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    archivos: Mapped[list["ArchivoDocumentoProyecto"]] = relationship(
        "ArchivoDocumentoProyecto", back_populates="documento",
        cascade="all, delete-orphan", order_by="ArchivoDocumentoProyecto.id",
    )


class ArchivoDocumentoProyecto(Base):
    """Un archivo montado en una casilla del expediente.

    Una casilla admite varios: el item 08 lleva seis certificados de
    calibracion (uno por transformador) y el 26 lleva una foto por equipo.
    Por eso los archivos son una tabla hija y no una columna `url` en la casilla.
    """

    __tablename__ = "documentos_proyecto_archivo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documentos_proyecto.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    origen: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=OrigenArchivo.LINK)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    nombre_archivo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tamano_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tipo_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subido_por: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    documento: Mapped["DocumentoProyecto"] = relationship(
        "DocumentoProyecto", back_populates="archivos")


class ParametroProyecto(Base):
    """El valor de un dato del proyecto. Una fila por dato, no por documento.

    La identidad de un parametro es (proyecto, clave, equipo_tipo, posicion):

      - clave           que dato es, del catalogo. Ej. "medidor.numero_de_serie".
      - equipo_tipo     a que equipo pertenece. La misma clave sirve para el
                        medidor principal y el de respaldo; los distingue esta
                        columna. Vacia para los datos del proyecto.
      - equipo_posicion cual de los equipos de ese tipo. Los TC y TP van de 1 a
                        3 (fases R, S, T). Cero para lo que no se repite.

    equipo_tipo y equipo_posicion no admiten NULL a proposito: en Postgres dos
    NULL no colisionan, asi que con columnas nulables la restriccion de unicidad
    no habria impedido guardar el mismo parametro dos veces. Con '' y 0 si.

    El valor se guarda tres veces a proposito: `valor` es el texto exacto tal
    como lo escribio el usuario (es lo que se imprime en los formatos oficiales
    y no puede perder ni un decimal), y `valor_numero` / `valor_fecha` son la
    version tipada que llenan los servicios segun el tipo declarado en el
    catalogo, para poder filtrar, ordenar y disparar alertas de vencimiento.
    """

    __tablename__ = "parametros_proyecto"
    __table_args__ = (
        UniqueConstraint("proyecto_id", "clave", "equipo_tipo", "equipo_posicion",
                         name="uq_parametros_proyecto_clave"),
        Index("ix_parametros_proyecto_clave", "clave"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    clave: Mapped[str] = mapped_column(String(120), nullable=False)
    equipo_tipo: Mapped[str] = mapped_column(String(40), nullable=False, server_default="")
    equipo_posicion: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    valor: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_numero: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    valor_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)

    # De que documento salio este valor. Es la fuente de verdad del dato y lo
    # unico de la relacion documento-parametro que es dato de operacion: cual
    # de los documentos que pueden contenerlo fue el que efectivamente se uso.
    documento_origen_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documentos_proyecto.id", ondelete="SET NULL"),
        nullable=True,
    )
    verificado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    actualizado_por: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    documento_origen: Mapped["DocumentoProyecto | None"] = relationship(
        "DocumentoProyecto", foreign_keys=[documento_origen_id])
