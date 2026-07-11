"""Development / testing utility: create tables from the models and seed data.

This is a convenience for rapid local development and tests -- it creates the
schema directly from ``Base.metadata`` and loads the initial seed data.

Schema management in production is handled exclusively by Alembic. All DDL that
this script used to apply on every run (the old ``add_columns()`` helper) has
been consolidated into version-controlled Alembic migrations (see migrations
047 and 048). Run ``alembic upgrade head`` to bring a database to the current
schema; use this script only for a fresh local/test database.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    seed()


if __name__ == "__main__":
    init()
