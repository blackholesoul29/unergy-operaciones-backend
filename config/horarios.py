"""Cuándo corre cada tarea programada. El QUÉ está en `apps/<dominio>/tasks.py`.

Un solo archivo en vez de 19 decoradores repartidos: así se ve de un vistazo qué
compite con qué por una franja, que es justo la información que hacía falta al
escribir estos horarios (dos jobs que leen la misma API con rate limit no pueden
salir el mismo segundo).

**Todo en hora de Bogotá.** `CELERY_TIMEZONE` es `America/Bogota` (UTC−5, sin
horario de verano) aunque el contenedor corra en UTC, igual que hacía el
`BackgroundScheduler` de FastAPI con `timezone=settings.TIMEZONE`. Sin eso, la
clasificación de las 3:30am correría a las 10:30pm del día anterior.

`django_celery_beat` guarda el horario en la BASE, pero su `DatabaseScheduler`
sincroniza este diccionario al arrancar: la fuente de verdad sigue siendo el
código, versionado y revisable, y la tabla es solo su reflejo. Editar una franja
desde el admin funciona hasta el próximo arranque, que la vuelve a pisar.
"""

from celery.schedules import crontab

# Franjas heredadas tal cual del scheduler de FastAPI. Los comentarios explican
# las que NO son obvias — por qué esa hora y no otra.
HORARIOS = {
    # ── Reporte de Energía ───────────────────────────────────────────────────
    "reporte-energia-clasificar": {
        "task": "energia.reporte_diario",
        "schedule": crontab(hour=3, minute=30),
    },
    # Cada 5 min de 4:00 a 5:30. Dos entradas porque un crontab no expresa
    # minutos distintos según la hora.
    "reporte-energia-drift-4am": {
        "task": "energia.drift_medidores",
        "schedule": crontab(hour=4, minute="*/5"),
    },
    "reporte-energia-drift-5am": {
        "task": "energia.drift_medidores",
        "schedule": crontab(hour=5, minute="0,5,10,15,20,25,30"),
    },
    # Cada 15 min de 4 a 6, más un último intento a las 6:00 en punto: el correo
    # de Cedillanos llega entre las 3:25 y las 6:10 y el reporte cierra a las 6.
    "excel-cedillanos": {
        "task": "energia.excel_cedillanos",
        "schedule": crontab(hour="4,5", minute="*/15"),
    },
    "excel-cedillanos-ultimo": {
        "task": "energia.excel_cedillanos",
        "schedule": crontab(hour=6, minute=0),
    },

    # ── Madrugada: los tres que leen la API de generación de Unergy ──────────
    # Separados 10 y 15 min entre sí a propósito, para no competir por el mismo
    # rate limit en el mismo segundo.
    "gen-promedio-recalcular": {
        "task": "proyectos.recalcular_gen_promedio",
        "schedule": crontab(hour=3, minute=20),
    },
    "backfill-comercializacion": {
        "task": "energia.backfill_comercializacion",
        "schedule": crontab(hour=3, minute=30),
    },
    "comercial-backfill": {
        "task": "comercial.backfill_oportunidades",
        "schedule": crontab(hour=3, minute=35),
    },

    # ── Comercial ────────────────────────────────────────────────────────────
    # Justo después del cambio de día, para que el tablero amanezca correcto.
    "comercial-cierres": {
        "task": "comercial.cerrar_contratos_vencidos",
        "schedule": crontab(hour=0, minute=20),
    },
}
