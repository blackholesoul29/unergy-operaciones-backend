"""Ningun modulo del arbol Django puede usar un nombre que no existe.

Bug real (2026-09-05): el clasificador del Reporte de Energia fallaba para
TODAS las fronteras con

    name 'MIN_DIAS_FORMA' is not defined

`MIN_DIAS_FP`, `MIN_DIAS_FORMA` y `MIN_DIAS_CONSUMO` estan definidas en
`app/services/reporte_energia/historial.py` (lineas 21-23) y el port a
`apps/energia/services/reporte/historial.py` se las dejo atras, pero siguio
usandolas. Lo mismo con cuatro esquemas Pydantic que `vistas.py` y
`correcciones.py` usaban sin importar.

Es la tercera cara de la misma clase de bug del port --un nombre que no
existe-- despues del `select_related("operador")` de fronteras
(test_querysets_compilan.py) y el `duration_hours` de mantenimiento-impacto
(test_serializers_construibles.py). Y es la mas barata de detectar: `ruff` la
encuentra sin importar el modulo, sin base de datos y sin red.

**Por que hace falta un test y no basta con correr el linter en CI**: el
proyecto no tiene `pytest-django`, asi que la capa Django no tiene ni un test
que la ejecute. Este archivo es la red que si corre en cada `pytest`.

El BASELINE de abajo es deuda conocida, no una excepcion permanente: son
modulos que ya estaban rotos antes de este test y que nadie ha reportado
todavia. Cada uno es un `NameError` esperando a que alguien abra esa vista. La
lista solo puede ENCOGER -- si un modulo aparece con mas nombres rotos de los
que declara, o aparece uno nuevo, el test falla.
"""
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PAQUETES = ["apps", "api", "config"]

# Modulo -> cuantos nombres indefinidos tiene hoy. Al arreglar uno, BAJAR el
# numero (o borrar la linea): el test exige que no suba.
BASELINE = {
    # Ninguno de estos lo ha reportado nadie todavia. Cada linea es una vista
    # que responde 500 --o una tarea que muere-- en cuanto alguien la use.
    "apps/mercado_xm/services/cumplimiento/simulador.py": 12,
    "apps/mercado_xm/services/cumplimiento/cierre.py": 6,
    "apps/mercado_xm/services/cumplimiento/transada.py": 2,
    "apps/mercado_xm/services/cumplimiento/panel.py": 2,
    "apps/proyectos/services/pendientes.py": 2,
    "apps/contabilidad/services/panel.py": 1,
    # Anotacion de tipo en texto (`-> "django.db.models.QuerySet"`): nunca se
    # evalua en tiempo de ejecucion, asi que no rompe nada. Se deja declarada
    # para que el conteo cuadre.
    "apps/monitoreo/services/fallas/consultas.py": 1,
}

_SEPARADOR = "\n  "


def _nombres_indefinidos() -> Counter:
    """`{ruta relativa: cuantos}` segun ruff. Counter vacio si todo esta bien."""
    proceso = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821",
         "--no-cache", "--output-format", "concise", *PAQUETES],
        cwd=RAIZ, capture_output=True, text=True,
    )
    encontrados: Counter = Counter()
    for linea in proceso.stdout.splitlines():
        if "F821" not in linea:
            continue
        # ruff usa el separador del sistema; se normaliza para que el BASELINE
        # se escriba una sola vez y valga en Windows y en el contenedor.
        ruta = linea.split(":")[0].replace("\\", "/")
        encontrados[ruta] += 1
    return encontrados


@pytest.fixture(scope="module")
def hallazgos() -> Counter:
    pytest.importorskip("ruff", reason="requiere ruff (uv sync)")
    return _nombres_indefinidos()


def test_ningun_modulo_nuevo_usa_un_nombre_inexistente(hallazgos):
    nuevos = sorted(set(hallazgos) - set(BASELINE))
    assert not nuevos, (
        "Estos modulos usan un nombre que no existe. Cada uno revienta con "
        "NameError en cuanto se ejecute esa linea -- nada lo detecta antes:"
        + _SEPARADOR
        + _SEPARADOR.join(f"{m} ({hallazgos[m]})" for m in nuevos)
    )


def test_ningun_modulo_conocido_empeora(hallazgos):
    peores = [
        f"{m}: {hallazgos[m]} ahora, {BASELINE[m]} en el baseline"
        for m in sorted(BASELINE) if hallazgos.get(m, 0) > BASELINE[m]
    ]
    assert not peores, (
        "Se agregaron nombres inexistentes:" + _SEPARADOR + _SEPARADOR.join(peores)
    )


def test_el_baseline_no_declara_deuda_que_ya_no_existe(hallazgos):
    """Si alguien arregla un modulo, hay que bajar su numero -- si no, el
    baseline deja de reflejar la realidad y protege menos de lo que dice."""
    resueltos = [
        f"{m}: {hallazgos.get(m, 0)} ahora, {BASELINE[m]} declarados"
        for m in sorted(BASELINE) if hallazgos.get(m, 0) < BASELINE[m]
    ]
    assert not resueltos, (
        "Ya se arreglaron nombres que el baseline sigue declarando. Bajar el "
        "numero (o borrar la linea):" + _SEPARADOR + _SEPARADOR.join(resueltos)
    )
