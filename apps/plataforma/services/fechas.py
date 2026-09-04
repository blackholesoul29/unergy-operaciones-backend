"""La fecha de hoy en Colombia.

El contenedor corre en UTC (`TIME_ZONE = "UTC"` en config/settings.py) y
Colombia es UTC−5 sin horario de verano: entre las 19:00 y medianoche de Bogota
el servidor ya esta en el dia siguiente. `date.today()` en ese rango adelanta un
dia todo lo que dependa de "hoy" (CLAUDE.md).

Vive en `plataforma` porque no es de ningun dominio: es del reloj. Las copias de
`garantias/services/calculo.py` y `energia/services/solenium_monitoreo.py` son
anteriores a este modulo y deberian converger aca.
"""

from datetime import date, datetime, timedelta, timezone

_COL_TZ = timezone(timedelta(hours=-5))


def hoy_col() -> date:
    return datetime.now(_COL_TZ).date()
