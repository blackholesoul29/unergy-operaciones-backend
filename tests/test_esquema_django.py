"""Los modelos y las migraciones de Django no se separan.

Desde el 2026-09-04 Django posee el esquema: `managed` es el default en los 119
modelos de dominio, `makemigrations` genera DDL real y Alembic quedó congelado
en la revisión 143. Esta prueba reemplaza a `test_frontera_esquema.py`, que
vigilaba lo contrario — que ningún modelo fuera gestionado— y quedó sin objeto.

**El modo de fallo cambió de lugar, no desapareció.** Antes el riesgo era
declarar una columna en el modelo sin la revisión de Alembic que la crea; el
síntoma era un 500 semanas después. Ahora es cambiar un modelo y no generar su
migración: `migrate` no tiene nada que aplicar, la base se queda como estaba y
el 500 llega igual. La diferencia es que ahora se puede detectar sin tocar la
base, comparando el estado de las migraciones contra los modelos — que es
exactamente lo que hace `makemigrations --check`.

Lo que esta prueba NO puede ver es si la base real coincide con las migraciones:
para eso hace falta una conexión, y eso vive en `scripts/verificar_esquema_django.py`,
que corre en el arranque del deploy.
"""

import os

import pytest

# Apps de terceros que traen sus propios modelos. No son dominio nuestro y sus
# migraciones las mantiene el paquete, así que quedan fuera de estas dos
# comprobaciones.
APPS_DE_TERCEROS = {"contenttypes", "django_celery_beat"}


@pytest.fixture(scope="module")
def django_listo():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    import django

    django.setup()


@pytest.fixture(scope="module")
def modelos(django_listo):
    from django.apps import apps

    return [
        m for m in apps.get_models()
        if m._meta.app_label not in APPS_DE_TERCEROS
    ]


def test_todo_modelo_de_dominio_lo_gestiona_django(modelos):
    """Un modelo con `managed = False` es invisible para `makemigrations`.

    No falla ni avisa: la tabla simplemente nunca recibe el cambio, y como ya no
    hay un Alembic detrás que lo provisione, la columna no la crea nadie.
    """
    sin_gestionar = [
        f"{m._meta.app_label}.{m.__name__} (tabla {m._meta.db_table})"
        for m in modelos if not m._meta.managed
    ]
    assert not sin_gestionar, (
        "Estos modelos quedaron fuera del control de Django. Desde que Alembic se "
        "congeló nadie más provisiona su esquema — quita el `managed = False`:\n  "
        + "\n  ".join(sorted(sin_gestionar))
    )


def test_no_hay_cambios_de_modelo_sin_su_migracion(django_listo):
    """`makemigrations --check`: los modelos y las migraciones dicen lo mismo.

    Se llama al autodetector directamente en vez de al comando: no necesita base
    de datos, y el mensaje puede nombrar la app y la operación que falta en vez
    de un código de salida.
    """
    from django.apps import apps
    from django.db.migrations.autodetector import MigrationAutodetector
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
    from django.db.migrations.state import ProjectState

    cargador = MigrationLoader(None, ignore_no_migrations=True)
    autodetector = MigrationAutodetector(
        cargador.project_state(),
        ProjectState.from_apps(apps),
        NonInteractiveMigrationQuestioner(specified_apps=set(), dry_run=True),
    )
    cambios = autodetector.changes(graph=cargador.graph)

    pendientes = [
        f"{app}: {op.describe()}"
        for app, migraciones in sorted(cambios.items())
        if app not in APPS_DE_TERCEROS
        for m in migraciones
        for op in m.operations
    ]
    assert not pendientes, (
        "Hay cambios en los modelos sin su migración. Corre "
        "`python manage.py makemigrations` y commitea el archivo junto al "
        "modelo:\n  " + "\n  ".join(pendientes)
    )
