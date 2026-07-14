"""Clasificación mensual estandarizada del rol de cada planta en el mercado.

Seis categorías (a-f) según el agente (UNGG generador / UNGC comercializador),
el mercado (PPA / bolsa) y el rol (venta / compra). Es la ESTANDARIZACIÓN
consultable vía API de las piscinas del tab PPA/proyectos de Cumplimiento:
otras áreas y sistemas pueden consumir `GET /clasificacion-energia` sin
reimplementar la lógica GESCON.

La tabla es un snapshot materializado por (año, mes): se recalcula desde
GESCON/PPA al consultarla (o vía refresh) — no se edita a mano. Una planta
puede tener VARIAS filas en un mes (p. ej. aporta a un PPA de venta y además
se compra en bolsa para otro contrato, o PPA compra + venta en bolsa UNGC).
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# ── Catálogo estandarizado (fuente única de las 6 categorías) ────────────────
# key = identificador estable para API/BD. No renombrar sin migración.
CATEGORIAS_ENERGIA = [
    {
        "key": "ppa_venta_ungg", "letra": "a", "agente": "UNGG",
        "mercado": "ppa", "rol": "venta", "label": "PPA Venta (UNGG)",
        "descripcion": "Plantas en contratos GESCON donde UNGG le vende a otro "
                       "agente (Terpel, NEU, etc.). Incluye plantas en 'uso del "
                       "recurso' (cliente en bolsa; se le liquida a precio bolsa), "
                       "marcadas con uso_del_recurso=true.",
        "regla_pendiente": False,
    },
    {
        "key": "ppa_compra_ungc", "letra": "b", "agente": "UNGC",
        "mercado": "ppa", "rol": "compra", "label": "PPA Compra (UNGC)",
        "descripcion": "Contratos en que UNGC compra energía a algún agente en "
                       "GESCON (usualmente a UNGG).",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_compra_ungg", "letra": "c", "agente": "UNGG",
        "mercado": "bolsa", "rol": "compra", "label": "Compra en Bolsa (UNGG)",
        "descripcion": "Compras de UNGG a precio de bolsa. Hoy: plantas "
                       "duplicadas que aportan a un contrato con origen bolsa. "
                       "Incluye la compra interna de 'uso del recurso' "
                       "(uso_del_recurso=true): el vendedor es el cliente dueño "
                       "de la planta, no el mercado. Los contratos PLC entrarán "
                       "aquí cuando se liquiden en plataforma.",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_compra_ungc", "letra": "d", "agente": "UNGC",
        "mercado": "bolsa", "rol": "compra", "label": "Compra en Bolsa (UNGC)",
        "descripcion": "UNGC comprando en bolsa. Reglas de negocio aún por "
                       "definir: la categoría existe reservada, sin filas.",
        "regla_pendiente": True,
    },
    {
        "key": "bolsa_venta_ungg", "letra": "e", "agente": "UNGG",
        "mercado": "bolsa", "rol": "venta", "label": "Venta en Bolsa (UNGG)",
        "descripcion": "Plantas sin contrato vigente en GESCON: venden en bolsa "
                       "desde UNGG como generador.",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_venta_ungc", "letra": "f", "agente": "UNGC",
        "mercado": "bolsa", "rol": "venta", "label": "Venta en Bolsa (UNGC)",
        "descripcion": "UNGC le compra la energía a UNGG (usualmente a precio "
                       "de bolsa) para venderla en bolsa — SIC vigente con "
                       "comprador UNGC.",
        "regla_pendiente": False,
    },
]

CATEGORIAS_KEYS = {c["key"] for c in CATEGORIAS_ENERGIA}


class ClasificacionEnergiaMensual(Base):
    """Una fila = una planta clasificada en una categoría durante un mes,
    opcionalmente ligada al contrato PPA que motiva la clasificación."""

    __tablename__ = "clasificacion_energia_mensual"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    categoria: Mapped[str] = mapped_column(String(32), nullable=False)  # key del catálogo

    proyecto_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=False
    )
    contrato_ppa_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ppa_contratos.id", ondelete="SET NULL"), nullable=True
    )
    codigo_sic: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # True si la fila proviene de la figura "uso del recurso": la planta clasifica
    # doble — (a) venta PPA + (c) compra interna al cliente a precio bolsa.
    uso_del_recurso: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    # ventana con la que la planta participa en la categoría (informativa)
    fecha_inicio: Mapped[object] = mapped_column(Date, nullable=True)
    fecha_fin: Mapped[object] = mapped_column(Date, nullable=True)

    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    proyecto = relationship("Proyecto", lazy="joined")
    contrato_ppa = relationship("PPAContrato", lazy="joined")

    __table_args__ = (
        Index("ix_clasif_energia_mes", "anio", "mes"),
        Index("ix_clasif_energia_mes_cat", "anio", "mes", "categoria"),
        Index("ix_clasif_energia_proyecto", "proyecto_id"),
    )
