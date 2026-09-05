"""La fecha de hoy en Colombia.

El contenedor corre en UTC (`TIME_ZONE = "UTC"` en config/settings.py) y
Colombia es UTC−5 sin horario de verano: entre las 19:00 y medianoche de Bogota
el servidor ya esta en el dia siguiente. `date.today()` en ese rango adelanta un
dia todo lo que dependa de "hoy" (CLAUDE.md).

Vive en `plataforma` porque no es de ningun dominio: es del reloj. Las copias de
`garantias/services/calculo.py` es anterior a este modulo y deberia converger
aca. La de `energia/services/solenium_monitoreo.py` murio con ese archivo al
migrar generacion solar a SolarView.
"""

from datetime import date, datetime, timedelta, timezone

COL_TZ = timezone(timedelta(hours=-5))
_COL_TZ = COL_TZ   # nombre anterior; se conserva porque ya hay quien lo importa


def hoy_col() -> date:
    return datetime.now(COL_TZ).date()


def ahora_col() -> datetime:
    """El instante actual CON zona. Para sellar un `resolved_at` o comparar
    contra una columna `timestamptz`, donde la fecha sola no alcanza."""
    return datetime.now(COL_TZ)
