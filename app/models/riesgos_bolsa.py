"""Modelos del módulo Descubrimientos y Gestión de Riesgos de Bolsa.

`PrecioBolsa` es la serie horaria canónica del precio de bolsa (mercado de
energía) en COP/MWh sobre la que el módulo calcula la exposición financiera.

Complementa —no reemplaza— las tablas crudas `precios_bolsa_diario` y
`precios_bolsa_horario` que llena el proxy EVO (ver app/api/v1/evo_proxy.py):
aquéllas guardan el reporte diario/horario tal como lo entrega EVO en COP/kWh;
ésta es una serie normalizada (una fila por hora, COP/MWh) alimentada desde los
archivos de XM vía app/utils/xm_parser.py.
"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Numeric, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.models.base import Base


class PrecioBolsa(Base):
    __tablename__ = "precio_bolsa"
    __table_args__ = (
        # UNIQUE crea el índice; una hora sólo puede tener un precio.
        Index("ix_precio_bolsa_fecha_hora", "fecha_hora", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Sin timezone (hora local del mercado), igual que el DDL de la spec.
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    precio_cop_mwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
