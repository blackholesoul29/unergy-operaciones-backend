"""Tests standalone: `python scripts/tests/test_merge_proyectos.py`.

(1) Valida que TODA la config de fusión (_MERGE_*) referencia tablas y columnas que
    existen de verdad en el esquema (metadata SQLAlchemy). Un typo de tabla/columna
    -> el test revienta, no producción.
(2) Prueba funcional sobre SQLite en memoria de los 4 patrones SQL de la fusión:
    repunte simple, descarte por colisión (unique compuesto), descarte 1-a-1, y
    copia de campo escalar único liberando primero al perdedor.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import app.models  # registra todos los modelos en Base.metadata
from app.models import Base
from app.api.v1.proyectos import (
    _MERGE_SIMPLE, _MERGE_COMPOSITE, _MERGE_ONE_TO_ONE, _MERGE_SCALAR_UNIQUE,
)


def test_config_referencia_tablas_y_columnas_reales():
    tablas = Base.metadata.tables

    def cols(t):
        assert t in tablas, f"tabla inexistente en el esquema: {t}"
        return {c.name for c in tablas[t].columns}

    for t in _MERGE_SIMPLE:
        assert "proyecto_id" in cols(t), f"{t} sin columna proyecto_id"

    for t, keys in _MERGE_COMPOSITE:
        c = cols(t)
        assert "proyecto_id" in c, f"{t} sin proyecto_id"
        for k in keys:
            assert k in c, f"{t} sin columna de clave única '{k}'"

    for t in _MERGE_ONE_TO_ONE:
        assert "proyecto_id" in cols(t), f"{t} sin proyecto_id"

    asic = cols("asic_cambios_contratos")
    assert {"proyecto_original_id", "proyecto_nuevo_id"} <= asic

    proy = cols("proyectos")
    assert "proyecto_padre_id" in proy
    for f in _MERGE_SCALAR_UNIQUE:
        assert f in proy, f"proyectos sin campo escalar único '{f}'"


def test_patrones_sql_de_fusion_en_sqlite():
    from sqlalchemy import create_engine, text
    e = create_engine("sqlite://")
    p = {"keeper": 1, "loser": 2}
    with e.begin() as db:
        db.execute(text("CREATE TABLE proyectos (id INTEGER PRIMARY KEY, sub_project TEXT UNIQUE)"))
        db.execute(text("CREATE TABLE fallas (id INTEGER PRIMARY KEY, proyecto_id INT)"))
        db.execute(text("CREATE TABLE liquidaciones (id INTEGER PRIMARY KEY, proyecto_id INT, periodo TEXT, UNIQUE(proyecto_id, periodo))"))
        db.execute(text("CREATE TABLE proyecto_info_tecnica (id INTEGER PRIMARY KEY, proyecto_id INT UNIQUE)"))
        # ganador=1 (sub_project NULL), perdedor=2 (sub_project='api-x')
        db.execute(text("INSERT INTO proyectos (id, sub_project) VALUES (1, NULL), (2, 'api-x')"))
        # fallas: 2 del perdedor (repunte simple)
        db.execute(text("INSERT INTO fallas (proyecto_id) VALUES (2), (2)"))
        # liquidaciones: ganador tiene '2026-01'; perdedor tiene '2026-01' (colisión) y '2026-02' (se mueve)
        db.execute(text("INSERT INTO liquidaciones (proyecto_id, periodo) VALUES (1,'2026-01'), (2,'2026-01'), (2,'2026-02')"))
        # info_tecnica: solo el perdedor -> se mueve (ganador no tiene)
        db.execute(text("INSERT INTO proyecto_info_tecnica (proyecto_id) VALUES (2)"))

        # 1) simple
        db.execute(text("UPDATE fallas SET proyecto_id=:keeper WHERE proyecto_id=:loser"), p)
        # 2) compuesto: descartar colisión, mover resto
        db.execute(text("DELETE FROM liquidaciones WHERE proyecto_id=:loser AND EXISTS "
                        "(SELECT 1 FROM liquidaciones k WHERE k.proyecto_id=:keeper AND k.periodo = liquidaciones.periodo)"), p)
        db.execute(text("UPDATE liquidaciones SET proyecto_id=:keeper WHERE proyecto_id=:loser"), p)
        # 3) 1-a-1: ganador no tiene -> se mueve
        db.execute(text("DELETE FROM proyecto_info_tecnica WHERE proyecto_id=:loser AND EXISTS "
                        "(SELECT 1 FROM proyecto_info_tecnica k WHERE k.proyecto_id=:keeper)"), p)
        db.execute(text("UPDATE proyecto_info_tecnica SET proyecto_id=:keeper WHERE proyecto_id=:loser"), p)
        # 4) escalar único: liberar perdedor y copiar al ganador (estaba NULL)
        db.execute(text("UPDATE proyectos SET sub_project=NULL WHERE id=:loser"), p)
        db.execute(text("UPDATE proyectos SET sub_project='api-x' WHERE id=:keeper"), p)
        db.execute(text("DELETE FROM proyectos WHERE id=:loser"), p)

        # Verificaciones
        assert db.execute(text("SELECT count(*) FROM fallas WHERE proyecto_id=1")).scalar() == 2
        # liquidaciones del ganador: '2026-01' (suya) + '2026-02' (movida) = 2; la colisión se descartó
        periodos = sorted(r[0] for r in db.execute(text("SELECT periodo FROM liquidaciones WHERE proyecto_id=1")))
        assert periodos == ["2026-01", "2026-02"], periodos
        assert db.execute(text("SELECT count(*) FROM liquidaciones")).scalar() == 2  # no quedó la colisión
        assert db.execute(text("SELECT proyecto_id FROM proyecto_info_tecnica")).scalar() == 1
        assert db.execute(text("SELECT sub_project FROM proyectos WHERE id=1")).scalar() == "api-x"
        assert db.execute(text("SELECT count(*) FROM proyectos WHERE id=2")).scalar() == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(fns)} tests pasaron.")
