"""Seed initial data. Schema is owned by Alembic — see docs/MIGRATIONS.md.

Schema creation/evolution is handled exclusively by Alembic migrations
(`alembic upgrade head`). This script no longer runs any DDL by default; it only
seeds catalog/reference data.

For a local-only fresh database you may set ``CREATE_ALL_ON_STARTUP=true`` to let
SQLAlchemy create the ORM-mapped tables via ``Base.metadata.create_all`` instead
of running migrations. This is intended for quick local/test setups only and must
NOT be used in production, where Alembic is the single source of truth.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def _create_all_if_requested() -> None:
    """Optionally create ORM tables for local/test convenience only.

    Production must rely on ``alembic upgrade head`` instead. Note this only
    creates ORM-mapped tables; the raw-SQL-only tables live in the Alembic
    baseline migration, so a real fresh setup should use Alembic.
    """
    if os.environ.get("CREATE_ALL_ON_STARTUP", "").lower() == "true":
        print("CREATE_ALL_ON_STARTUP=true → running Base.metadata.create_all (local/dev only)...")
        Base.metadata.create_all(bind=engine)
        print("Tables created.")
    else:
        print("Skipping create_all — schema is managed by Alembic (alembic upgrade head).")


def init():
    _create_all_if_requested()
    seed()


if __name__ == "__main__":
    init()
