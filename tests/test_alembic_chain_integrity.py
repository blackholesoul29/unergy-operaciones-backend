"""Integridad de la cadena de migraciones Alembic.

Estas pruebas son ESTÁTICAS (parsean los archivos, no importan Alembic ni la
base de datos) para poder correr en cualquier entorno de CI sin dependencias.

Atrapan, en cada PR, la clase de fallo recurrente que rompe el deploy:

  * ids de `revision` duplicados entre ramas que se forkearon de master en
    momentos distintos (ej. dos archivos con ``revision = "020"``). Es el fallo
    MÁS grave y es SILENCIOSO: Alembic indexa por id, así que el segundo archivo
    desaparece del grafo, ``upgrade`` reporta éxito, estampa el id — y esa
    migración ya no puede correr nunca;
  * `down_revision` colgante que no apunta a ninguna revisión existente;
  * que el deploy use ``alembic upgrade head`` (singular) en vez de ``heads``.

*Heads* múltiples SÍ están permitidos: con una cola de PRs, varias ramas se
forkean de master a la vez y cada una queda como head independiente. Exigir un
único head obligaría a re-linealizar toda la cola a mano en cada merge, y una
sola rama rechazada dejaría colgante a todas las siguientes. La solución es
``alembic upgrade heads`` (plural) en `start.sh`, que aplica todas las ramas en
cualquier orden de merge. Lo único que debe ser único es el **id**.

PERO eso tiene un costo que debes conocer ANTES de escribir tu migración: con
varios heads en master, Alembic ya no sabe sobre cuál construir.

  * ``alembic revision`` falla con "Multiple heads are present". Ramifica
    explícitamente: ``alembic revision --head <id> -m "..."`` (o escribe el
    archivo a mano, que es lo que hace este repo).
  * ``alembic downgrade -1`` es AMBIGUO con varios heads: baja una rama
    arbitraria. Nombra la revisión: ``alembic downgrade <id>``.
  * Cuando la cola de merges se drene, colapsa los heads con un solo
    ``alembic merge heads`` y master vuelve a tener un head único.
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


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Solo líneas EJECUTABLES: si el guard mirara el archivo entero, un `alembic upgrade
# heads` comentado lo dejaría verde mientras el deploy no migra nada.
_UPGRADE_RE = re.compile(r"alembic\s+upgrade\s+(heads|head)\b")


def _executable_upgrade_calls(text):
    """[(nº línea, 'head'|'heads')] de cada `alembic upgrade` NO comentado."""
    out = []
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0]  # descarta comentarios de shell
        m = _UPGRADE_RE.search(line)
        if m:
            out.append((i, m.group(1)))
    return out


def test_start_sh_upgrades_all_heads():
    """El deploy debe correr `alembic upgrade heads` (plural), y de verdad.

    Varias ramas se forkean de master al mismo tiempo y cada una aporta un head
    independiente. Con `head` singular Alembic aborta con "Multiple head
    revisions" y el servidor arranca SIN ninguna migración aplicada. `heads`
    aplica todas las ramas, en cualquier orden de merge.
    """
    with open(os.path.join(REPO_ROOT, "start.sh"), encoding="utf-8") as fh:
        calls = _executable_upgrade_calls(fh.read())

    assert calls, (
        "start.sh no ejecuta ningún `alembic upgrade` (¿comentado?). El deploy "
        "arrancaría sin aplicar migraciones."
    )
    singulares = [n for n, form in calls if form == "head"]
    assert not singulares, (
        f"start.sh usa `alembic upgrade head` (singular) en la(s) línea(s) {singulares}. "
        "Con cualquier bifurcación, el deploy salta TODAS las migraciones y el "
        "servidor arranca con el esquema viejo. Usa `heads`."
    )


def test_no_other_runner_uses_singular_head():
    """Ningún OTRO script del repo puede reintroducir el `head` singular.

    El fix de `start.sh` no sirve de nada si mañana un Dockerfile, un workflow de
    CI o un Makefile corre `alembic upgrade head` por su cuenta.
    """
    ofensores = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", "node_modules", "__pycache__", ".venv", "venv", "tests"}
        ]
        for fname in filenames:
            if not (
                fname.endswith((".sh", ".yml", ".yaml", ".toml", ".py"))
                or fname.startswith(("Dockerfile", "Makefile", "Procfile"))
            ):
                continue
            path = os.path.join(dirpath, fname)
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            for num, form in _executable_upgrade_calls(text):
                if form == "head":
                    ofensores.append(f"{os.path.relpath(path, REPO_ROOT)}:{num}")

    assert not ofensores, (
        f"`alembic upgrade head` (singular) en: {ofensores}. Con varias ramas en cola "
        "eso aborta con 'Multiple head revisions' y no aplica NINGUNA migración. "
        "Usa `heads`."
    )
