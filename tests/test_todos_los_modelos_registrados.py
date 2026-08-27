"""app/models/__init__.py debe importar TODOS los módulos de app/models/ --
si un modelo nuevo no se agrega ahí, `import app.models` (usado por varios
tests como forma de "registrar todo en Base.metadata", ver
test_server_defaults_ddl.py y test_modelo_vs_ddl.py) no lo incluye. La
tabla de ese modelo queda cubierta solo por accidente, si ALGÚN OTRO test
la importa primero en la misma corrida -- y eso depende del orden de
colección, que no es una garantía real.

Encontrado en producción 2026-08-26: `garantias_ajustes.py` e `informes.py`
existían como modelos reales (con tabla en Postgres) pero ninguno de los
dos estaba en `app/models/__init__.py` -- confirmado corriendo la suite con
el orden de archivos invertido: dos casos de
test_server_defaults_ddl.py::test_el_ddl_no_lleva_comillas_duplicadas
desaparecían de la colección sin ningún error, solo menos cobertura."""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "app" / "models"

# __init__.py no necesita re-importar estos -- no son módulos de modelo real.
_EXCLUIR = {"__init__.py", "base.py"}


def _archivos_de_modelo() -> set[str]:
    return {p.stem for p in MODELS_DIR.glob("*.py") if p.name not in _EXCLUIR}


def _modulos_importados_en_init() -> set[str]:
    init_src = (MODELS_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(init_src, filename=str(MODELS_DIR / "__init__.py"))
    modulos = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.models."):
            # "app.models.fronteras" -> "fronteras"
            modulos.add(node.module.rsplit(".", 1)[-1])
    return modulos


def test_todo_archivo_de_modelo_esta_importado_en_models_init():
    archivos = _archivos_de_modelo()
    importados = _modulos_importados_en_init()
    faltantes = archivos - importados

    assert not faltantes, (
        f"Estos módulos de app/models/ tienen un modelo real pero "
        f"app/models/__init__.py no los importa -- `import app.models` no "
        f"registra sus tablas en Base.metadata de forma confiable (queda "
        f"a merced de qué otro test los importe primero): {sorted(faltantes)}. "
        f"Agregá un `from app.models.<archivo> import <Clase>` en __init__.py."
    )
