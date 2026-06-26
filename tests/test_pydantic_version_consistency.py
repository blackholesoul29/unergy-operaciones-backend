"""Guardia anti-regresión: el backend debe correr en Pydantic V2 puro.

Estos tests no migran nada (el repo ya está en V2); evitan que vuelva a
introducirse Pydantic V1.

Aclaración clave: `pydantic.v1` SIEMPRE es importable en un entorno V2 porque
es un submódulo de compatibilidad que viene dentro del propio paquete Pydantic
V2. Por eso NO comprobamos que `import pydantic.v1` falle (fallaría el test),
sino que ningún archivo del proyecto lo importe.
"""
import re
from pathlib import Path

import pydantic

REPO_ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"guardian", ".venv", "venv", "node_modules", "__pycache__", ".git"}
V1_IMPORT = re.compile(
    r"\bfrom\s+pydantic\.v1\b|\bimport\s+pydantic\.v1\b|\bfrom\s+pydantic\s+import\s+v1\b"
)


def _source_files():
    for target in ("app", "tests", "scripts"):
        base = REPO_ROOT / target
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
                continue
            yield path


def test_pydantic_is_v2():
    assert pydantic.VERSION.startswith("2."), (
        f"Se esperaba Pydantic V2, instalado: {pydantic.VERSION}"
    )


def test_pydantic_settings_is_v2():
    import pydantic_settings

    assert pydantic_settings.VERSION.startswith("2."), (
        f"Se esperaba pydantic-settings V2, instalado: {pydantic_settings.VERSION}"
    )


def test_no_pydantic_v1_imports_in_source():
    offenders = []
    for path in _source_files():
        if path.name == Path(__file__).name:
            continue  # este archivo contiene el patrón en regex/comentarios
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if V1_IMPORT.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()}")
    assert not offenders, "Imports de Pydantic V1 encontrados:\n" + "\n".join(offenders)
