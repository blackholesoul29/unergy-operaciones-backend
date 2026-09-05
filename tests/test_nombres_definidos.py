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

El BASELINE de abajo esta VACIO: los 26 casos que quedaban en otros dominios
(cumplimiento, contabilidad, proyectos) se arreglaron el mismo dia. Existe
como mecanismo por si alguna vez hace falta declarar deuda a proposito, pero
cada entrada seria un `NameError` en produccion esperando a que alguien abra
esa vista, asi que lo normal es que siga vacio.
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
BASELINE: dict[str, int] = {
    # VACIO, y asi tiene que quedarse. Los 26 que existian el 2026-09-05 --12 en
    # el simulador de cumplimiento, 6 en su cierre, 2 en transada, 2 en su
    # panel, 2 en pendientes de proyectos, 1 en el panel de contabilidad y 1
    # anotacion de tipo en fallas-- se arreglaron todos ese mismo dia.
    #
    # Si alguna vez hay que volver a poner algo aca, que sea con fecha y con la
    # razon: una entrada en este diccionario es un NameError en produccion
    # esperando a que alguien abra esa vista.
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
