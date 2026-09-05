"""Lo que sale por una respuesta de DRF tiene que ser un dict, no un modelo Pydantic.

Bug real (2026-09-05): la pestana Resumen del Reporte de Energia mostraba
"NaN dias-frontera reportados en el rango" y las barras vacias.

DRF **no** serializa un modelo Pydantic como objeto: lo RECORRE. Un `BaseModel`
itera dando pares `(clave, valor)`, asi que `JSONRenderer` produce

    [[["etiqueta","CGM"],["total",7]]]        <- lista de listas

donde el contrato dice

    [{"etiqueta":"CGM","total":7}]            <- lista de objetos

El frontend leia `d.total` sobre una lista, obtenia `undefined`, y
`reduce((s, i) => s + i.total, 0)` daba NaN. Nada falla: ni el backend, ni el
render, ni el typecheck -- el tipo declarado en types.ts es correcto, solo que
lo que llega no lo cumple.

Es el mismo modo de fallo de siempre en este port: **una diferencia de FORMA no
lanza excepcion**. En FastAPI devolver un modelo Pydantic era lo normal; el port
conservo esas construcciones dentro de servicios que ahora responden por DRF.

Este test es de codigo fuente a proposito: no hace falta base de datos ni
levantar el servidor para saber que un servicio del arbol Django no debe
construir modelos Pydantic. Los esquemas de `app/schemas/` siguen siendo el
contrato escrito -- lo que no puede es viajar el OBJETO.
"""
import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PAQUETES = ("apps", "api")


def _modulos_python():
    for paquete in PAQUETES:
        for ruta in (RAIZ / paquete).rglob("*.py"):
            if "migrations" in ruta.parts:
                continue  # generadas, no responden nada
            yield ruta


def _importa_esquemas_pydantic(arbol: ast.AST) -> list[str]:
    """`from app.schemas... import X` y `from pydantic import BaseModel`."""
    encontrados = []
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.ImportFrom) or not nodo.module:
            continue
        if nodo.module.startswith("app.schemas"):
            encontrados.append(f"from {nodo.module} import "
                               + ", ".join(a.name for a in nodo.names))
        elif nodo.module == "pydantic" and any(
            a.name == "BaseModel" for a in nodo.names
        ):
            encontrados.append("from pydantic import BaseModel")
    return encontrados


def test_hay_modulos_que_revisar():
    """Sanity: si el recorrido se rompe, el test pasaria vacio."""
    assert len(list(_modulos_python())) > 100


def test_ningun_servicio_django_arma_respuestas_con_pydantic():
    fallos = []
    for ruta in _modulos_python():
        try:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for linea in _importa_esquemas_pydantic(arbol):
            fallos.append(f"{ruta.relative_to(RAIZ).as_posix()}: {linea}")

    assert not fallos, (
        "Estos modulos del arbol Django traen esquemas Pydantic. Si alguno de "
        "esos objetos llega a un `Response(...)`, DRF lo serializa como lista "
        "de pares clave-valor y el cliente recibe una forma que no cumple el "
        "contrato -- sin ningun error, ni aca ni en el frontend. Devolver "
        "dicts planos:\n  " + "\n  ".join(sorted(fallos))
    )


def test_drf_efectivamente_deforma_un_modelo_pydantic():
    """Fija el porque del test de arriba, para que no se lea como una regla
    de estilo. Si una version futura de DRF o Pydantic cambiara esto, este
    test falla y avisa que la prohibicion ya no hace falta."""
    import os

    pydantic = pytest.importorskip("pydantic")
    django = pytest.importorskip("django", reason="requiere el entorno de Django")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ.setdefault("SECRET_KEY", "x" * 40)
    django.setup()
    renderers = pytest.importorskip("rest_framework.renderers")

    class Item(pydantic.BaseModel):
        etiqueta: str
        total: int

    salida = renderers.JSONRenderer().render([Item(etiqueta="CGM", total=7)])

    assert salida != b'[{"etiqueta":"CGM","total":7}]', (
        "DRF ya serializa modelos Pydantic como objetos: revisar si sigue "
        "haciendo falta prohibirlos en los servicios."
    )
