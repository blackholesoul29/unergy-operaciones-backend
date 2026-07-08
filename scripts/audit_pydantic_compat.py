#!/usr/bin/env python
"""
Auditoría de compatibilidad Pydantic V2 sobre app/.

Escanea el árbol de fuentes en busca de sintaxis heredada de Pydantic V1 que
todavía "funciona" en V2 pero emite DeprecationWarning (o directamente falla):

  * imports de pydantic.v1 (el shim de compatibilidad V1)
  * herencia de BaseConfig
  * la clase anidada  ``class Config:``  (reemplazar por model_config = ConfigDict(...))
  * decoradores @validator / @root_validator  (usar @field_validator / @model_validator)
  * llaves de config exclusivas de V1 (orm_mode, allow_population_by_field_name, schema_extra…)
  * acceso a __config__
  * helpers de instancia V1 (.parse_obj, parse_obj_as, .from_orm, update_forward_refs…)

Uso:
    python scripts/audit_pydantic_compat.py [ruta]   # por defecto: app/

Sale con código 1 si encuentra alguna infracción (útil en CI), 0 si está limpio.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# (etiqueta, regex). Se aplican línea por línea sobre cada .py.
CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("import de pydantic.v1", re.compile(r"\bfrom\s+pydantic\.v1\b|\bimport\s+pydantic\.v1\b|\bfrom\s+pydantic\s+import\s+v1\b")),
    ("herencia de BaseConfig", re.compile(r"\bBaseConfig\b")),
    ("clase anidada `class Config`", re.compile(r"^\s*class\s+Config\b")),
    ("decorador V1 @validator/@root_validator", re.compile(r"^\s*@(?:root_)?validator\b")),
    ("llave de config V1", re.compile(
        r"\b(?:orm_mode|allow_population_by_field_name|allow_mutation|"
        r"anystr_strip_whitespace|min_anystr_length|max_anystr_length|"
        r"underscore_attrs_are_private|copy_on_model_validation|keep_untouched|"
        r"schema_extra)\b\s*=")),
    ("acceso a __config__", re.compile(r"\.__config__\b")),
    ("helper de instancia V1", re.compile(
        r"\b(?:parse_obj_as|\.parse_obj\(|\.parse_raw\(|\.from_orm\(|"
        r"update_forward_refs\(|\.schema_json\()")),
    ("Field V1 (const=/regex=)", re.compile(r"\bField\([^)]*\b(?:const|regex)\s*=")),
]

# Comentarios/otros que no debemos marcar aunque contengan la palabra clave.
def _is_noise(label: str, line: str) -> bool:
    stripped = line.lstrip()
    # No marcar líneas de comentario puro (excepto imports, que nunca son comentario).
    if stripped.startswith("#"):
        return True
    return False


def audit(root: Path) -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in CHECKS:
                if pattern.search(line) and not _is_noise(label, line):
                    findings.append((path, lineno, label, line.strip()))
    return findings


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("app")
    if not root.exists():
        print(f"[audit] ruta no encontrada: {root}", file=sys.stderr)
        return 2

    findings = audit(root)
    if not findings:
        print(f"[audit] OK — sin sintaxis Pydantic V1 en {root}/")
        return 0

    print(f"[audit] {len(findings)} infracción(es) de Pydantic V1 en {root}/:\n")
    for path, lineno, label, snippet in findings:
        print(f"  {path}:{lineno}  [{label}]")
        print(f"      {snippet}")
    print("\n[audit] Migra a sintaxis V2 (ConfigDict / field_validator / model_validator).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
