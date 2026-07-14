"""Lógica pura del CRM comercial (testeable sin BD)."""
from datetime import datetime, timedelta, timezone

# Estados donde aplica la alerta de días sin respuesta. `fin` queda por fuera
# a propósito: es cierre comercial y los históricos migrados viven ahí.
ESTADOS_CON_ALERTA = frozenset({"prospeccion", "oferta", "negociacion"})


def col_now() -> datetime:
    """Ahora en hora Colombia (UTC-5, sin DST) — patrón del repo."""
    return datetime.now(timezone.utc) - timedelta(hours=5)


def calcular_alerta(
    estado: str,
    estado_desde: datetime,
    ultima_gestion: datetime | None,
    umbral_dias: int,
    ahora: datetime,
) -> tuple[int, bool]:
    """Devuelve (dias_sin_respuesta, alerta).

    La referencia es lo MÁS RECIENTE entre la entrada al estado actual y la
    última gestión de bitácora. Alerta solo con MÁS de `umbral_dias` días
    (5 días exactos NO alertan) y solo en ESTADOS_CON_ALERTA.
    """
    # Defensivo: si algún datetime viene naive (p.ej. roundtrip por un backend
    # sin timezone), se alinea al tz de `ahora` para no romper la resta.
    def _com(dt):
        if dt is not None and dt.tzinfo is None and ahora.tzinfo is not None:
            return dt.replace(tzinfo=ahora.tzinfo)
        return dt

    estado_desde = _com(estado_desde)
    ultima_gestion = _com(ultima_gestion)
    referencia = estado_desde
    if ultima_gestion is not None and ultima_gestion > referencia:
        referencia = ultima_gestion
    dias = (ahora - referencia).days
    if dias < 0:
        dias = 0
    alerta = estado in ESTADOS_CON_ALERTA and dias > umbral_dias
    return dias, alerta
