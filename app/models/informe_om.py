import enum
from datetime import date, datetime
from sqlalchemy import BigInteger, String, Text, Date, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class EstadoInformeOMEnum(str, enum.Enum):
    borrador = "borrador"
    en_revision = "en_revision"
    aprobado = "aprobado"


class ProyectoInformeOM(Base):
    """Ficha de Puesta en Marcha / O&M de un proyecto -- fusiona lo que antes
    eran dos pestañas y dos tablas separadas (Inicio de Operación +
    Informe de Puesta en Marcha) en un solo modelo (2026-08-31).

    `proyecto_inicio_operacion` perdió su único editor el 2026-08-21 y quedó
    con 2 filas de prototipo, sin ningún endpoint que las pudiera seguir
    escribiendo -- un proyecto nuevo no tenía forma de completar fechas,
    checklist ni pendientes. Esta tabla fusiona esos campos acá, donde sí
    hay un PUT real, en vez de mantener dos tablas donde una está muerta.

    Una fila por proyecto. Los 4 `checklist_*` cubren solo las categorías que
    ya se resumían en un semáforo (Fusion Solar, Frontera, Estación meteo,
    Reconectador) -- el resto del catálogo viejo (CCTV, cableado MT/BT,
    transformadores, tableros, shelter, obras civiles, paneles, trackers,
    checklist detallado por inversor) no se revive, nunca tuvo lector real.
    Inversores/frontera en vivo siguen viniendo de Solenium/Gaia al servir
    el detalle -- no se duplican acá.
    """
    __tablename__ = "proyecto_informe_om"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=False, unique=True, index=True
    )

    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elaborado_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actividad: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # borrador -> en_revision -> aprobado. Reemplaza el envío a
    # InformeGuardado/app/api/v1/informes.py (sistema genérico compartido con
    # Mensuales/Portafolio/Ranking, revisor hardcodeado por email,
    # desconectado de esta ficha): acá el estado vive en la propia fila y el
    # PDF siempre se arma desde el contenido actual, nunca una foto vieja.
    estado: Mapped[str] = mapped_column(
        SAEnum(EstadoInformeOMEnum, name="estado_informe_om_enum"),
        nullable=False, server_default="borrador",
    )

    # Fusionados desde proyecto_inicio_operacion (ver docstring de la clase):
    empresa_contratista: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fecha_energizacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicio_operacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    # [ { descripcion, responsable, fecha_compromiso, clasificacion, estado, observaciones } ]
    pendientes = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Checklist de comisionamiento -- solo las 4 categorías con semáforo real,
    # cada una con su propio schema Pydantic en app/schemas/informe_om.py
    # (no dict[str, Any] suelto como el `checklist` viejo sin esquema).
    checklist_fusion_solar = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    checklist_frontera = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    checklist_estacion_meteo = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    checklist_reconectador = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    # { objetivo, alcance_items: [] }
    objetivo_alcance = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # { seguidores_marca, medida_comercial_marca, medida_comercial_modelo,
    #   plataformas_monitoreo: [], responsable_nombre, responsable_email }
    datos_generales = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # { enlace_principal, enlaces_celulares, concentrador_datos, destino_datos, sincronizacion_horaria }
    arquitectura_comunicacion = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # [ { descripcion, marca, cantidad, ubicacion, numero_serie } ]
    equipos = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # [ { variable, unidad, fuente, registro, plataforma } ]
    variables_monitoreadas = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # { notificaciones: [...], umbrales_alarma: [...], politicas_datos: [...] }
    configuracion_monitoreo = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # [ { codigo, prueba, criterio_aceptacion, resultado, observacion } ]
    protocolo_pruebas = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # [ { codigo, descripcion, causa_raiz, accion_correctiva, estado } ]
    eventos_operativos = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # { generales, factor_pendiente }
    observaciones = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # [str]
    recomendaciones = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [ { nombre, cargo, fecha } ]
    firmas = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # [ { id, nombre, url, tamaño, tipo_mime, created_at } ] -- Anexo B (diagrama)
    evidencia_arquitectura = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    proyecto: Mapped["Proyecto"] = relationship("Proyecto")
