"""Guardas de integridad de la cadena de migraciones Alembic.

Contexto: builds autónomos (daemon) ramificaron desde master en momentos
distintos y cada uno añadió revisiones "020" y "024" → ids duplicados + 4 heads.
Con varios heads, `alembic upgrade head` falla ("Multiple head revisions are
present") y `start.sh` solo emite WARNING, así que NINGUNA migración corre.

Estos tests fallan si se reintroduce un id duplicado o se bifurca la cadena.
"""
import os

import pytest

ALEMBIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "alembic"
)


def _script_dir():
    alembic = pytest.importorskip("alembic")  # noqa: F841
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", ALEMBIC_DIR)
    return ScriptDirectory.from_config(cfg)


def test_single_head():
    """`alembic upgrade head` debe ser inequívoco: exactamente un head."""
    sd = _script_dir()
    heads = sd.get_heads()
    assert len(heads) == 1, (
        f"Se esperaba 1 head, hay {len(heads)}: {sorted(heads)}. "
        "Un id de revisión duplicado o una cadena bifurcada rompe "
        "`alembic upgrade head`."
    )


def test_no_duplicate_revision_ids():
    """Ningún id de revisión puede aparecer en más de un archivo."""
    sd = _script_dir()
    seen = {}
    for rev in sd.walk_revisions():
        seen.setdefault(rev.revision, []).append(rev.path)
    dupes = {r: paths for r, paths in seen.items() if len(paths) > 1}
    assert not dupes, f"Ids de revisión duplicados: {dupes}"


def test_chain_reaches_base_from_head():
    """El head debe encadenar hasta la base sin revisiones colgantes."""
    sd = _script_dir()
    (head,) = sd.get_heads()
    revs = list(sd.walk_revisions("base", head))
    assert revs, "La cadena de revisiones está vacía."
    # La última revisión recorrida no tiene padre (es la base).
    assert revs[-1].down_revision is None
