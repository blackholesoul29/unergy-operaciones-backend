from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings

# The declarative Base lives in app.models.base. Re-exported here so it is
# reachable as `app.core.database.Base` too — Alembic's target_metadata is
# `Base.metadata`, which must reflect every ORM model for autogeneration.
from app.models.base import Base  # noqa: E402,F401

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
