"""Seed initial data.

Schema management lives entirely in Alembic. Run the migrations first:

    alembic upgrade head

then run this script to populate initial/seed data. No DDL is executed here.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.seeds.seed_data import seed


def init():
    seed()


if __name__ == "__main__":
    init()
