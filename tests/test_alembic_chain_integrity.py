"""Integridad de la cadena de migraciones Alembic.

Estas pruebas son ESTÁTICAS (parsean los archivos, no importan Alembic ni la
base de datos) para poder correr en cualquier entorno de CI sin dependencias.

Atrapan, en cada PR, la clase de fallo recurrente que rompe el deploy:

  * ids de `revision` duplicados entre ramas que se forkearon de master en
    momentos distintos (ej. dos archivos con ``revision = "020"``);
  * múltiples *heads* (cadena bifurcada) → ``alembic upgrade head`` lanza
    "Multiple head revisions" y el deploy salta TODAS las migraciones;
  * `down_revision` colgante que no apunta a ninguna revisión existente.

Si esta prueba falla, NO mergees a master hasta relinealizar la cadena a un
único head con ids únicos.
"""
import os
import re
from collections import Counter

VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic",
    "versions",
)

_REVISION_RE = re.compile(r"^revision(?:\s*:[^=]+)?\s*=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN_RE = re.compile(r"^down_revision(?:\s*:[^=]+)?\s*=\s*(.+)$", re.M)


def _parse_migrations():
    """Lista plana de (revision_id, filename, [down_revision_ids...]).

    Plana a propósito: NO se indexa por revision_id para que un id duplicado no
    colapse dos archivos en una sola entrada (lo cual podría enmascarar un
    down_revision colgante que apunte a un id duplicado).
    """
    out = []
    for fname in sorted(os.listdir(VERSIONS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        text = open(os.path.join(VERSIONS_DIR, fname), encoding="utf-8").read()
        rid_m = _REVISION_RE.search(text)
        if not rid_m:
            continue
        rid = rid_m.group(1)
        down_m = _DOWN_RE.search(text)
        downs = []
        if down_m:
            # Cubre "019", ("019", "020"), Union[str, None] = "019", None
            downs = re.findall(r"['\"]([^'\"]+)['\"]", down_m.group(1))
        out.append((rid, fname, downs))
    return out


def test_no_duplicate_revision_ids():
    """Ningún id de `revision` debe repetirse entre archivos."""
    ids = []
    for fname in sorted(os.listdir(VERSIONS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        text = open(os.path.join(VERSIONS_DIR, fname), encoding="utf-8").read()
        for m in _REVISION_RE.findall(text):
            ids.append(m)
    dups = {rid: n for rid, n in Counter(ids).items() if n > 1}
    assert not dups, f"ids de revisión duplicados (rompen Alembic): {dups}"


def test_all_down_revisions_resolve():
    """Cada `down_revision` debe apuntar a una revisión existente (o None)."""
    migs = _parse_migrations()
    known = {rid for rid, _fname, _downs in migs}
    dangling = []
    for rid, _fname, downs in migs:
        for d in downs:
            if d not in known:
                dangling.append((rid, d))
    assert not dangling, f"down_revision colgante (no existe): {dangling}"


def test_single_head():
    """La cadena debe tener exactamente un head (sin bifurcaciones)."""
    migs = _parse_migrations()
    referenced = set()
    for _rid, _fname, downs in migs:
        referenced.update(downs)
    all_ids = {rid for rid, _fname, _downs in migs}
    heads = sorted(rid for rid in all_ids if rid not in referenced)
    assert len(heads) == 1, (
        f"se esperaba 1 head, hay {len(heads)}: {heads}. "
        "`alembic upgrade head` fallará y el deploy saltará las migraciones."
    )
