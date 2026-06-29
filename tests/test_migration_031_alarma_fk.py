"""Regresión: la migración 031 debe ser segura en una BD nueva.

`alarma_estado` NO la crea ninguna migración ni el `create_all` de
`init_db.py`: nace del DDL de arranque (`_PENDING_DDLS` en `app/main.py`), que
corre DESPUÉS de `alembic upgrade head` (ver `start.sh`). Por eso 031 debe
saltar el ALTER/DELETE cuando la tabla todavía no existe; de lo contrario el
deploy de una BD nueva deja Alembic atascado bajo head ("relation
alarma_estado does not exist").

Estas pruebas no tocan una BD real: parchan el proxy `alembic.op` con un bind
falso y verifican el comportamiento de la guarda (tabla ausente → 0 DDL; tabla
presente → se emite el ADD CONSTRAINT con ON DELETE CASCADE).
"""
import importlib.util
import os

from alembic import op

VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic",
    "versions",
)
MIGRATION_PATH = os.path.join(VERSIONS_DIR, "031_alarma_estado_fk_cascade.py")


def _load_migration():
    spec = importlib.util.spec_from_file_location("_mig031", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeBind:
    """Devuelve `regclass` (presente/ausente) para el SELECT to_regclass."""

    def __init__(self, table_exists):
        self._regclass = "alarma_estado" if table_exists else None

    def execute(self, _stmt):
        return _FakeResult(self._regclass)


def _patch_op(monkeypatch, table_exists):
    executed = []
    monkeypatch.setattr(op, "get_bind", lambda: _FakeBind(table_exists))
    monkeypatch.setattr(op, "execute", lambda sql: executed.append(str(sql)))
    return executed


def test_upgrade_noop_when_table_absent(monkeypatch):
    """BD nueva: tabla aún inexistente → NINGÚN DDL (lo crea el DDL de arranque)."""
    executed = _patch_op(monkeypatch, table_exists=False)
    _load_migration().upgrade()
    assert executed == [], (
        "031 ejecutó DDL sobre alarma_estado inexistente — rompería el deploy de "
        f"una BD nueva (Alembic atascado bajo head). DDL emitido: {executed}"
    )


def test_upgrade_adds_cascade_fk_when_table_present(monkeypatch):
    """Prod existente: la tabla ya existe → impone la FK ON DELETE CASCADE."""
    executed = _patch_op(monkeypatch, table_exists=True)
    _load_migration().upgrade()
    joined = " ".join(executed).lower()
    assert any("delete from alarma_estado" in s.lower() for s in executed), executed
    assert "add constraint fk_alarma_estado_proyecto_id" in joined, executed
    assert "on delete cascade" in joined, executed


def test_downgrade_noop_when_table_absent(monkeypatch):
    """Downgrade también guarda: tabla ausente → nada que revertir, 0 DDL."""
    executed = _patch_op(monkeypatch, table_exists=False)
    _load_migration().downgrade()
    assert executed == [], executed


def test_downgrade_drops_constraint_when_table_present(monkeypatch):
    executed = _patch_op(monkeypatch, table_exists=True)
    _load_migration().downgrade()
    joined = " ".join(executed).lower()
    assert "drop constraint if exists fk_alarma_estado_proyecto_id" in joined, executed
