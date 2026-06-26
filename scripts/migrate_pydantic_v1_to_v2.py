#!/usr/bin/env python3
"""Auditoría Pydantic V1 → V2.

Escanea recursivamente el código fuente del backend en busca de imports y
sintaxis propias de Pydantic V1, y reporta cualquier hallazgo con archivo y
línea. Sirve como guardia anti-regresión: el repo ya está 100% en Pydantic V2,
así que en condiciones normales no debe encontrar nada.

Notas importantes:
  - `pydantic.v1` es un submódulo de compatibilidad que viene *dentro* de
    Pydantic V2. Su existencia no implica que el proyecto use V1; lo que importa
    es que NINGÚN archivo lo importe.
  - `class Config` aún funciona en V2 pero el estilo idiomático es
    `model_config = ConfigDict(...)`; se reporta como aviso, no como error.

Uso:
    python3 scripts/migrate_pydantic_v1_to_v2.py            # escanea app/ y tests/
    python3 scripts/migrate_pydantic_v1_to_v2.py app otra/  # rutas a medida

Salida: código 0 si no hay imports V1; 1 si encuentra alguno.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ["app", "tests"]
EXCLUDE_DIRS = {"guardian", ".venv", "venv", "node_modules", "__pycache__", ".git"}

# Imports V1 explícitos: error duro.
V1_IMPORT = re.compile(r"\bfrom\s+pydantic\.v1\b|\bimport\s+pydantic\.v1\b|\bfrom\s+pydantic\s+import\s+v1\b")

# Sintaxis V1 que debería migrarse a V2: avisos.
V1_SYNTAX = {
    "@validator": re.compile(r"@validator\b"),
    "@root_validator": re.compile(r"@root_validator\b"),
    "validate_always": re.compile(r"\bvalidate_always\b"),
    "orm_mode": re.compile(r"\borm_mode\b"),
    "allow_population_by_field_name": re.compile(r"\ballow_population_by_field_name\b"),
    "schema_extra": re.compile(r"\bschema_extra\b"),
    "class Config (usar model_config=ConfigDict)": re.compile(r"^\s*class Config\b"),
}


def iter_py_files(targets: list[str]):
    for target in targets:
        base = (REPO_ROOT / target).resolve()
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
                continue
            yield path


def main(argv: list[str]) -> int:
    targets = argv[1:] or DEFAULT_TARGETS
    errors: list[str] = []
    warnings: list[str] = []

    for path in iter_py_files(targets):
        rel = path.relative_to(REPO_ROOT)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            stripped = line.lstrip()
            # Solo sentencias de import reales (evita coincidencias en docstrings/comentarios).
            if stripped.startswith(("from ", "import ")) and V1_IMPORT.search(line):
                errors.append(f"{rel}:{n}: import Pydantic V1 → {line.strip()}")
            if stripped.startswith("#"):
                continue
            for name, pat in V1_SYNTAX.items():
                if pat.search(line):
                    warnings.append(f"{rel}:{n}: sintaxis V1 [{name}] → {line.strip()}")

    if warnings:
        print("AVISOS (sintaxis V1 a modernizar):")
        for w in warnings:
            print(f"  {w}")
        print()

    if errors:
        print("ERRORES (imports de Pydantic V1):")
        for e in errors:
            print(f"  {e}")
        print(f"\n{len(errors)} import(s) de Pydantic V1 encontrados.")
        return 1

    print("OK: ningún import de Pydantic V1 en el código fuente.")
    if warnings:
        print(f"({len(warnings)} aviso(s) de sintaxis legacy — no bloquean).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
