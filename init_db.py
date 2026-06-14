"""Run once to apply the schema via Alembic and seed initial data."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.seeds.seed_data import seed

# Última revisión de la cadena incremental heredada (001..020). Esas migraciones
# NO son idempotentes y asumen que las tablas base ya existían (las creaba el
# viejo create_all), por lo que NO pueden correrse sobre una BD vacía. La
# migración 021 reconstruye el esquema completo desde los modelos
# (Base.metadata.create_all) y la 022 aplica los DDLs idempotentes que antes
# corrían en el arranque. Por eso "stampeamos" la 020 (sin ejecutarla) y luego
# hacemos upgrade a head: 021 (esquema) + 022 (DDLs extraídos).
_LEGACY_HEAD = "020"


def _alembic_config() -> Config:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(base_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    # Asegurar que Alembic apunte a la misma BD que usa la app.
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return cfg


def init():
    cfg = _alembic_config()
    print("Stamping legacy revision and applying migrations...")
    command.stamp(cfg, _LEGACY_HEAD)
    command.upgrade(cfg, "head")
    print("Schema up to date (alembic head).")
    seed()


if __name__ == "__main__":
    init()
