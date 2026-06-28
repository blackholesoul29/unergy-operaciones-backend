"""Regresión: el bootstrap (init_db.py) DEBE crear las tablas base antes de
sembrar datos.

Por qué existe esta prueba
--------------------------
El esquema base (clientes, proyectos, fallas, liquidaciones, ...) NO lo crea
ninguna migración Alembic: las migraciones 001..031 solo *alteran/extienden*
tablas que asumen ya existentes. Las tablas base provienen únicamente de
``Base.metadata.create_all`` en ``init_db.py`` (el bootstrap one-shot que
``start.sh`` ejecuta antes de ``alembic upgrade head``).

Si alguien vuelve a quitar ``create_all`` de ``init_db.py`` (como pasó al mover
los DDLs de arranque a Alembic), un despliegue contra una base de datos fresca
queda roto: ``init_db.py`` siembra sobre tablas inexistentes y ``alembic upgrade
head`` falla en la 001 al alterar una tabla que no existe. El CI no tiene una
base de datos real, así que esta prueba es estática/sin-DB: monkeypatchea
``create_all`` y ``seed`` y verifica el contrato y el ORDEN.
"""
import init_db


def test_init_creates_base_tables_before_seeding(monkeypatch):
    calls = []

    monkeypatch.setattr(
        init_db.Base.metadata, "create_all",
        lambda *a, **k: calls.append("create_all"),
    )
    monkeypatch.setattr(init_db, "seed", lambda: calls.append("seed"))

    init_db.init()

    # create_all DEBE correr, y ANTES de seed (sembrar requiere las tablas).
    assert calls == ["create_all", "seed"], (
        "init_db.init() debe crear las tablas base (create_all) y luego sembrar; "
        f"orden observado: {calls}"
    )


def test_create_all_binds_to_engine(monkeypatch):
    """create_all debe ejecutarse contra el engine de la app (no un bind nulo)."""
    seen = {}

    def _fake_create_all(*a, **k):
        seen["bind"] = k.get("bind", a[0] if a else None)

    monkeypatch.setattr(init_db.Base.metadata, "create_all", _fake_create_all)
    monkeypatch.setattr(init_db, "seed", lambda: None)

    init_db.init()

    assert seen.get("bind") is init_db.engine
