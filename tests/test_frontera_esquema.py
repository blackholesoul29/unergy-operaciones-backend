"""La frontera entre lo que posee Alembic y lo que posee Django.

`CLAUDE.md`: "Alembic es el ÚNICO camino para el esquema". Eso vale para las 115
tablas de dominio, pero no para todas: `contenttypes` y `django_celery_beat`
traen tablas propias que `manage.py migrate` crea. Esa es la **isla de Django**,
y lo que la hace segura es que no tiene ninguna arista hacia el esquema de
dominio — ni una clave foránea que Alembic pueda romper al reformar una tabla.

La frontera se rompe en silencio: basta olvidar `managed = False` en un modelo
nuevo para que el próximo `makemigrations` genere DDL sobre una tabla que
Alembic ya controla, y eso no falla hasta que alguien corre `migrate` en
producción. Esta prueba lo convierte en un fallo de build.

Al agregar una app de terceros con tablas propias se suma a `ISLA_DJANGO`, y esa
línea es la decisión: se está diciendo que sus tablas no referencian el dominio.
"""

import os

import pytest

# Tablas que Django crea y mantiene. Todo lo demás es de Alembic.
ISLA_DJANGO = {
    "django_content_type",
    "django_celery_beat_solarschedule",
    "django_celery_beat_intervalschedule",
    "django_celery_beat_clockedschedule",
    "django_celery_beat_crontabschedule",
    "django_celery_beat_periodictasks",
    "django_celery_beat_periodictask",
}

# Apps de dominio: sus modelos SIEMPRE son `managed = False`.
APPS_DE_DOMINIO = {
    "arriendos",
    "clientes",
    "comercial",
    "contabilidad",
    "contratos",
    "energia",
    "facturacion",
    "fronteras",
    "garantias",
    "liquidaciones",
    "mandatos",
    "mercado_xm",
    "monitoreo",
    "om",
    "plataforma",
    "ppa",
    "proyectos",
    "registros_cnd",
    "retos",
}


@pytest.fixture(scope="module")
def modelos():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    import django

    django.setup()
    from django.apps import apps

    return list(apps.get_models())


def test_ningun_modelo_de_dominio_es_gestionado_por_django(modelos):
    """Un modelo de dominio sin `managed = False` deja que Django emita DDL."""
    gestionados = [
        f"{m._meta.app_label}.{m.__name__} (tabla {m._meta.db_table})"
        for m in modelos
        if m._meta.app_label in APPS_DE_DOMINIO and m._meta.managed
    ]
    assert not gestionados, (
        "Estos modelos de dominio permitirían que Django genere DDL sobre tablas "
        "que Alembic ya controla. Agrega `managed = False` en su Meta:\n  "
        + "\n  ".join(sorted(gestionados))
    )


def test_la_isla_de_django_es_exactamente_la_declarada(modelos):
    """Una tabla gestionada que nadie declaró es una app instalada sin decidirlo."""
    real = {m._meta.db_table for m in modelos if m._meta.managed}

    nuevas = real - ISLA_DJANGO
    assert not nuevas, (
        "Django crearía tablas que no están declaradas en ISLA_DJANGO. Si la app "
        "es correcta, agrégalas ahí — esa línea afirma que sus tablas no "
        "referencian el esquema de dominio:\n  " + "\n  ".join(sorted(nuevas))
    )

    idas = ISLA_DJANGO - real
    assert not idas, (
        "ISLA_DJANGO declara tablas que ya ningún modelo crea; se desinstaló una "
        "app y quedó la línea:\n  " + "\n  ".join(sorted(idas))
    )
