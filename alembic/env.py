from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# La URL sale de Settings, no de alembic.ini: ahi vive el armado a partir de
# POSTGRES_*/PG_* y la normalizacion a postgresql+psycopg://. Antes esto tenia su
# propia copia del armado (con las variables RAILWAY_TCP_PROXY_*), y una copia de
# esa logica es justo lo que hace que Alembic apunte a otra base que la app.
from app.core.config import settings  # noqa: E402

# El `%%` no es adorno: set_main_option escribe en un configparser, que trata `%`
# como interpolacion. Una contrasena con caracteres especiales llega aca
# percent-encoded (quote_plus en config.py) y sin escapar revienta con
# "invalid interpolation syntax". get_main_option lo desescapa al leerlo.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

from app.models import Base  # noqa: E402 — must import after path setup
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
