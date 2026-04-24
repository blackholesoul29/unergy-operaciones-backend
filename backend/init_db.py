"""Run once to create all tables and seed initial data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import run_seeds
from app.core.database import SessionLocal


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    db = SessionLocal()
    try:
        run_seeds(db)
        print("Seed data loaded.")
    finally:
        db.close()


if __name__ == "__main__":
    init()
