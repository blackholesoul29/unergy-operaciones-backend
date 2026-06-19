"""Programmatic Alembic helpers.

Centralizes how the application brings the database schema up to date so that
both the FastAPI startup hook and ``init_db.py`` behave identically. Replaces the
old approach of running raw ``CREATE TABLE`` / ``ALTER TABLE`` DDL at startup.
"""
import os

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.core.database import engine

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALEMBIC_INI = os.path.join(_PROJECT_ROOT, "alembic.ini")


def get_alembic_config() -> Config:
    """Build an Alembic ``Config`` that works regardless of the process CWD."""
    cfg = Config(_ALEMBIC_INI)
    cfg.set_main_option("script_location", os.path.join(_PROJECT_ROOT, "alembic"))
    return cfg


def run_migrations() -> None:
    """Bring the database to ``head``.

    Handles the cases we actually see across environments:

    * Fresh/empty database -> applies every migration from the baseline.
    * Database already managed by this baseline -> applies only pending migrations.
    * Pre-existing schema created before Alembic was wired up (tables exist but
      there is no ``alembic_version`` table, e.g. DBs built by the old startup DDL),
      or a stale ``alembic_version`` left over from the previous, now-removed
      migration chain (a revision Alembic no longer knows about) -> stamp the
      current baseline as already applied so we don't try to re-create existing
      tables, then apply any newer migrations on top.
    """
    cfg = get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    known_revisions = {rev.revision for rev in script.walk_revisions()}

    tables = set(inspect(engine).get_table_names())
    has_schema = bool(tables - {"alembic_version"})

    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()

    # The DB has a schema, but Alembic either doesn't track it yet or tracks it
    # under a revision that no longer exists in the script history. Re-anchor it
    # on the current baseline instead of attempting to (re-)create tables.
    needs_stamp = has_schema and (current is None or current not in known_revisions)

    if needs_stamp:
        base_rev = script.get_bases()[0]
        # purge=True clears any stale alembic_version entry (e.g. a revision from
        # the previous migration chain) that Alembic can no longer resolve, then
        # records the current baseline as applied.
        command.stamp(cfg, base_rev, purge=True)

    command.upgrade(cfg, "head")
