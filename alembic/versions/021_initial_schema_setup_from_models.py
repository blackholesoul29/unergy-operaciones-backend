"""Initial schema setup from models

Crea todo el esquema actual a partir de ``Base.metadata`` (los modelos
SQLAlchemy son la fuente de verdad del esquema). Reemplaza al antiguo
``Base.metadata.create_all`` que se ejecutaba en ``init_db.py`` y en el
arranque de la app.

Notas sobre la cadena de migraciones:
- Las migraciones 001..020 son incrementales y asumen que las tablas base
  ya existían (las creaba ``create_all``). Por eso NO son auto-suficientes
  para una BD vacía. ``init_db.py`` hace ``alembic stamp 020`` antes de
  ``upgrade head`` para saltarlas y dejar que esta migración construya el
  esquema completo desde los modelos.
- ``create_all`` es idempotente (omite tablas existentes), de modo que esta
  migración es segura tanto en BD nuevas como en BD ya pobladas.

Revision ID: 021
Revises: 020
Create Date: 2026-06-14
"""
from alembic import op
from sqlalchemy import text

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.models import Base
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # Esta es la migración base del esquema: su reverso devuelve la BD al estado
    # vacío previo. No basta con ``Base.metadata.drop_all`` (solo conoce tablas de
    # modelo) porque la 022 crea tablas no-modelo (audit_log, om_*, etc.) que
    # dependen de tablas de modelo vía FK. Se barren todas las tablas y tipos enum
    # de ``public`` con CASCADE, preservando ``alembic_version``.
    op.execute(text(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename <> 'alembic_version'
            LOOP
                EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
            FOR r IN
                SELECT t.typname
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = 'public' AND t.typtype = 'e'
            LOOP
                EXECUTE 'DROP TYPE IF EXISTS public.' || quote_ident(r.typname) || ' CASCADE';
            END LOOP;
        END $$;
        """
    ))
