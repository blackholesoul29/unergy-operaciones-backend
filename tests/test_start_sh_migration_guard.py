"""Guardas del arranque (start.sh) frente al fallo silencioso de migraciones.

Contexto: start.sh tragaba el fallo de `alembic upgrade head` con un WARNING y
seguía arrancando el servidor → si la cadena tenía varios heads (ids duplicados),
NINGUNA migración corría y nadie se enteraba. Estos tests fijan que:

  1. start.sh aborta (exit != 0) cuando Alembic falla, en vez de continuar.
  2. start.sh hace un precheck de heads que aborta con varios heads.
  3. El comando de conteo de heads que usa start.sh devuelve exactamente 1 en la
     cadena actual (atrapa una re-bifurcación al mismo tiempo que el deploy real).
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START_SH = os.path.join(ROOT, "start.sh")


def _read_start_sh():
    with open(START_SH, encoding="utf-8") as fh:
        return fh.read()


def test_start_sh_aborts_on_alembic_failure():
    """El bloque de `alembic upgrade head` debe terminar con exit != 0, no WARNING."""
    src = _read_start_sh()
    # Aísla el bloque del comando (no el comentario) y exige `exit` no-cero.
    m = re.search(r"if !\s*alembic upgrade head;\s*then.*?\nfi", src, re.S)
    assert m, "No se encontró el bloque `if ! alembic upgrade head` en start.sh."
    block = m.group(0)
    assert re.search(r"exit\s+[1-9]", block), (
        "El fallo de `alembic upgrade head` debe abortar (exit != 0); "
        "tragárselo con un WARNING arranca el servidor sin migraciones."
    )


def test_start_sh_has_multiple_heads_precheck():
    """Debe existir un precheck que aborte cuando hay != 1 head."""
    src = _read_start_sh()
    assert "alembic heads" in src, "Falta el precheck de heads de Alembic."
    assert re.search(r'HEAD_COUNT.*!=\s*"1"', src) or re.search(
        r'\[\s*"\$HEAD_COUNT"\s*!=\s*"1"\s*\]', src
    ), "El precheck debe abortar cuando el número de heads no es 1."


def test_start_sh_is_not_swallowing_with_warning_only():
    """Regresión: ninguna rama de Alembic debe quedarse solo en WARNING+continuar."""
    src = _read_start_sh()
    # La única tolerancia permitida es init_db (lifespan reintenta el DDL).
    # Solo líneas ejecutables (ignora comentarios) para no romper si se reescribe
    # la prosa del encabezado.
    warning_lines = [
        ln
        for ln in src.splitlines()
        if not ln.lstrip().startswith("#") and "WARNING" in ln and "Alembic" in ln
    ]
    assert not warning_lines, (
        "Alembic no debe degradar a WARNING; debe abortar. "
        f"Líneas ofensivas: {warning_lines}"
    )


def test_head_count_command_yields_single_head():
    """El mismo pipeline de start.sh debe contar exactamente 1 head en la cadena.

    Replica `alembic heads | grep -c '(head)'`. Atrapa una re-bifurcación de la
    cadena con la MISMA señal que usa el deploy, no una aproximación.
    """
    pytest.importorskip("alembic")
    proc = subprocess.run(
        ["alembic", "heads"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # alembic emite warnings de ids duplicados por stderr; el conteo va por stdout.
    head_count = sum(1 for ln in proc.stdout.splitlines() if "(head)" in ln)
    assert head_count == 1, (
        f"Se esperaba 1 head, el pipeline de start.sh contó {head_count}. "
        f"stdout={proc.stdout!r}"
    )
