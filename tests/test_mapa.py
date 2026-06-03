"""Tests de _fix_url: normalización de esquemas de URL para psycopg3."""
from app.api.v1.mapa import _fix_url


def test_sqlalchemy_driver_scheme():
    assert _fix_url("postgresql+psycopg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_railway_postgres_scheme():
    # Railway/Heroku emiten postgres:// — psycopg3 lo rechaza; debe normalizarse.
    assert _fix_url("postgres://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_already_normalized_unchanged():
    assert _fix_url("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_empty_or_none_safe():
    assert _fix_url("") == ""
    assert _fix_url(None) is None
