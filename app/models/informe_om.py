from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.models.base import Base


class ProyectoInformeOM(Base):
    """Informe de Puesta en Marcha / O&M de un proyecto (pestaña "Informe" en
    Costos Variables, junto a Inicio de Operación).

    Una fila por proyecto. Solo guarda lo que Inicio de Operación NO captura
    (protocolo de pruebas, eventos operativos, inventario de equipos,
    arquitectura de comunicación, configuración de notificaciones/alarmas,
    narrativa). El resto (inversores, fechas, frontera, reconectador,
    estación meteo, monitoreo, pendientes) se lee en vivo de
    ProyectoInicioOperacion/Solenium/Gaia al servir el detalle -- no se
    duplica aquí.
    """
    __tablename__ = "proyecto_informe_om"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=False, unique=True, index=True
    )

    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elaborado_por: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actividad: Mapped[str | None] = mapped_column(String(255), nullable=True)

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
