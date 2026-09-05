"""Todo `ModelSerializer` de `api/v1/` tiene que poder construirse.

Bug real (2026-09-05): los cuatro endpoints de `mantenimiento-impacto`
respondian **500 en cada peticion** desde el despliegue de la migracion a
Django. `ImpactoSerializer.Meta.fields` pedia `duration_hours`, que en
SQLAlchemy era un `@hybrid_property` del modelo:

    ImproperlyConfigured: Field name `duration_hours` is not valid for model
    `MantenimientoImpacto` in ...ImpactoSerializer.

La causa es de la migracion misma, y por eso puede repetirse: los modelos de
`apps/*/models.py` los **genero** `scripts/generar_modelos_django.py` desde los
metadatos de SQLAlchemy, y ese generador lee COLUMNAS. Una propiedad de Python
no aparece en los metadatos, asi que se quedo atras mientras el serializer
seguia pidiendola.

Es la misma clase de bug que el 500 de fronteras (`select_related("operador")`
cuando el campo es `operador_red`, ver test_querysets_compilan.py): un nombre
que no existe, que nada valida hasta que alguien pide la vista. Los 2675 tests
pasaban con los dos endpoints caidos.

Construir el serializer es suficiente: DRF resuelve `Meta.fields`/`exclude`
contra el modelo en ese momento y levanta `ImproperlyConfigured` sobre cualquier
nombre que no sea campo, propiedad ni metodo `get_<campo>`. No hace falta base
de datos.
"""
import importlib
import inspect
import pkgutil

import pytest

django = pytest.importorskip("django", reason="requiere el entorno de Django (uv sync)")


@pytest.fixture(scope="module", autouse=True)
def _django_listo():
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    django.setup()


def _model_serializers():
    """`(ruta, clase)` de cada ModelSerializer declarado bajo `api/v1/`."""
    from rest_framework import serializers

    import api.v1 as raiz

    for info in pkgutil.iter_modules(raiz.__path__):
        try:
            modulo = importlib.import_module(f"api.v1.{info.name}.serializers")
        except ModuleNotFoundError:
            continue  # no todos los recursos tienen serializers.py
        for nombre, cls in vars(modulo).items():
            if not inspect.isclass(cls):
                continue
            if not issubclass(cls, serializers.ModelSerializer):
                continue
            if cls.__module__ != modulo.__name__:
                continue  # importado de otro lado
            if getattr(getattr(cls, "Meta", None), "model", None) is None:
                continue  # base abstracta
            yield f"{modulo.__name__}.{nombre}", cls


def test_hay_serializers_que_revisar():
    """Sanity: si el recorrido deja de encontrarlos, el test pasaria vacio."""
    encontrados = list(_model_serializers())
    assert len(encontrados) >= 50, f"solo se encontraron {len(encontrados)}"


def test_todo_model_serializer_se_puede_construir():
    from django.core.exceptions import ImproperlyConfigured

    fallos = []
    for ruta, cls in _model_serializers():
        try:
            cls().fields  # noqa: B018 -- construir los campos es lo que valida
        except ImproperlyConfigured as exc:
            fallos.append(f"{ruta} -> {exc}")
        except Exception:  # noqa: BLE001 -- del entorno, no de esta clase de bug
            continue

    assert not fallos, (
        "Hay serializers que no se pueden construir. Cada endpoint que los use "
        "responde 500 en todas sus peticiones:\n  "
        + ("\n  ").join(fallos)
    )
