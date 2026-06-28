"""Bootstrap the database: create the base tables, then load seed data.

Run once per fresh environment (also invoked by ``start.sh`` on every boot —
both steps are idempotent):

    python init_db.py        # create base tables (skips existing) + seed
    alembic upgrade head     # apply incremental migrations on top

Schema management is split on purpose:

  * **Base tables** come from the SQLAlchemy models (``Base.metadata.create_all``).
    This is the canonical bootstrap creator (idempotent — existing tables are
    skipped). It does NOT run inside the FastAPI app lifespan anymore, so
    application replicas never execute DDL on boot. (Migration 031 also calls
    create_all as a belt-and-suspenders for a migrate-only run — keep both.)
  * **Incremental schema changes** live in Alembic
    (``alembic/versions/`` — the ad-hoc boot-time column DDLs were consolidated
    into ``031_baseline_all_ddls.py``). Run ``alembic upgrade head`` after this.

No ad-hoc column DDLs run here anymore.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def init():
    print("Creating base tables (idempotent — skips existing)...")
    Base.metadata.create_all(bind=engine)
    print("Base tables ensured.")
    seed()


if __name__ == "__main__":
    init()
