"""Resolución de parámetros de configuración operativa.

Dado un tipo de parámetro y un proyecto opcional, devuelve el valor vigente de la
tabla `configuracion_operativa` resolviendo con prioridad:

  1. Configuración activa y vigente específica del proyecto.
  2. En su ausencia, la configuración activa y vigente global (proyecto_id NULL).

"Vigente" en la fecha de referencia `ref` (por defecto ahora): activo=True,
fecha_inicio <= ref y (fecha_fin es NULL o fecha_fin >= ref). Si hay varias
candidatas, gana la de `fecha_inicio` más reciente.

Reemplaza las constantes que antes vivían hardcodeadas en el estimador de impacto
de fallas (`app/api/v1/fallas.py`). `_DEFAULTS` conserva esos valores de
referencia como respaldo para entornos donde la tabla aún no está seedeada
(deploy nuevo, tests de funciones puras).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.configuracion_operativa import (
    ConfiguracionOperativa, TipoParametroConfigEnum,
)

TipoParametro = Union[TipoParametroConfigEnum, str]

# Valores de referencia históricos (mismos que las constantes originales de
# fallas.py). Se usan como respaldo cuando la BD no tiene una config vigente.
_DEFAULTS: dict[TipoParametroConfigEnum, float] = {
    TipoParametroConfigEnum.PRECIO_ENERGIA: 800.0,
    TipoParametroConfigEnum.CAPACIDAD_SOLAR: 0.18,
}

_SIN_DEFAULT = object()


class ConfiguracionNoEncontrada(Exception):
    """No existe configuración vigente (ni específica ni global) para el parámetro."""


def _tipo_valor(tipo: TipoParametro) -> str:
    return tipo.value if isinstance(tipo, TipoParametroConfigEnum) else str(tipo)


def resolver_configuracion(
    db: Session,
    tipo_parametro: TipoParametro,
    proyecto_id: Optional[int] = None,
    *,
    ref: Optional[datetime] = None,
) -> Optional[ConfiguracionOperativa]:
    """Devuelve la fila de configuración vigente (específica > global) o None."""
    tipo_val = _tipo_valor(tipo_parametro)
    if ref is None:
        ref = datetime.now(timezone.utc)

    base = db.query(ConfiguracionOperativa).filter(
        ConfiguracionOperativa.tipo_parametro == tipo_val,
        ConfiguracionOperativa.activo.is_(True),
        ConfiguracionOperativa.fecha_inicio <= ref,
        or_(
            ConfiguracionOperativa.fecha_fin.is_(None),
            ConfiguracionOperativa.fecha_fin >= ref,
        ),
    )

    if proyecto_id is not None:
        especifica = (
            base.filter(ConfiguracionOperativa.proyecto_id == proyecto_id)
            .order_by(ConfiguracionOperativa.fecha_inicio.desc())
            .first()
        )
        if especifica is not None:
            return especifica

    return (
        base.filter(ConfiguracionOperativa.proyecto_id.is_(None))
        .order_by(ConfiguracionOperativa.fecha_inicio.desc())
        .first()
    )


def obtener_valor(
    db: Session,
    tipo_parametro: TipoParametro,
    proyecto_id: Optional[int] = None,
    *,
    ref: Optional[datetime] = None,
    default=_SIN_DEFAULT,
) -> float:
    """Valor vigente del parámetro (específico del proyecto o global).

    Si no hay configuración vigente:
      - devuelve `default` cuando se proporciona explícitamente;
      - de lo contrario lanza `ConfiguracionNoEncontrada`.
    """
    cfg = resolver_configuracion(db, tipo_parametro, proyecto_id, ref=ref)
    if cfg is not None:
        return float(cfg.valor_float)
    if default is not _SIN_DEFAULT:
        return default
    raise ConfiguracionNoEncontrada(
        f"No hay configuración vigente para {_tipo_valor(tipo_parametro)} "
        f"(proyecto_id={proyecto_id})"
    )


def obtener_valor_o_defecto(
    db: Session,
    tipo_parametro: TipoParametroConfigEnum,
    proyecto_id: Optional[int] = None,
    *,
    ref: Optional[datetime] = None,
) -> float:
    """Como `obtener_valor` pero cae al valor de referencia (`_DEFAULTS`) si la BD
    no tiene config vigente. Pensado para cálculos que siempre deben producir un
    número (p. ej. la estimación de impacto de fallas) sin depender del seed."""
    return obtener_valor(
        db, tipo_parametro, proyecto_id,
        ref=ref, default=_DEFAULTS.get(tipo_parametro),
    )
