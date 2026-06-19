"""Run once to bring the schema to head (via Alembic) and seed initial data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.migrations import run_migrations
from app.seeds.seed_data import seed


def init():
    print("Applying database migrations (alembic upgrade head)...")
    run_migrations()
    print("Schema up to date.")
    seed()


if __name__ == "__main__":
    init()
