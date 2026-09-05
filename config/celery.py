"""Celery del proyecto.

Reemplaza al BackgroundScheduler que hoy vive DENTRO del proceso web
(`app/main.py`). Ese acoplamiento es la razon de `WORKERS=1`: con mas de un
worker de uvicorn cada uno arrancaba su propio scheduler y los jobs corrian
duplicados. Con el worker como servicio aparte esa restriccion desaparece.

Las colas replican el criterio de Origina (migration.md seccion 6): `tracker`
con una sola concurrencia porque ahi el orden importa.
"""

import os

from celery import Celery
from celery.signals import task_postrun, worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("operaciones")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# Los hijos de prefork heredan las conexiones del padre y nunca pasan por el
# ciclo de request de Django, que es quien normalmente las cierra. Sin estos dos
# hooks las conexiones se filtran hasta agotar el pool de PostgreSQL.
@worker_process_init.connect
def cerrar_conexiones_al_iniciar(**kwargs):
    from django.db import close_old_connections

    close_old_connections()


@task_postrun.connect
def cerrar_conexiones_tras_la_tarea(**kwargs):
    from django.db import close_old_connections

    close_old_connections()
