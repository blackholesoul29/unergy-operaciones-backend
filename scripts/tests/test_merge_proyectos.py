"""Tests standalone: `python scripts/tests/test_merge_proyectos.py`.

(1) Valida que TODA la config de fusión (_MERGE_*) referencia tablas y columnas que
    existen de verdad en el esquema (metadata SQLAlchemy, o la migración de Alembic
    para las tablas sin modelo ORM). Un typo de tabla/columna -> el test revienta,
    no producción.
(2) Prueba funcional sobre SQLite en memoria de los 4 patrones SQL de la fusión:
    repunte simple, descarte por colisión (unique compuesto), descarte 1-a-1, y
    copia de campo escalar único liberando primero al perdedor.
"""
import sys, os, re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import app.models  # registra todos los modelos en Base.metadata
from app.models import Base
from app.api.v1.proyectos import (
    _MERGE_SIMPLE, _MERGE_COMPOSITE, _MERGE_ONE_TO_ONE, _MERGE_SCALAR_UNIQUE,
)

# ── Tablas vivas en la base pero SIN modelo ORM ───────────────────────────────
# `Base.metadata` solo ve tablas con modelo. Cuando se retira una vista de producto
# se borra el modelo/schemas/router, pero la TABLA y sus filas siguen en la base y
# la fusión —que corre SQL crudo (`UPDATE {t} SET proyecto_id=...`)— DEBE seguir
# repuntándolas, o quedarían colgando de un proyecto borrado. Para estas se valida
# contra la migración que las crea, así el guard sigue atrapando typos y drops.
#
# REGLA: este set es solo para tablas vivas huérfanas por retiro de una vista, no un
# depósito de tablas zombis. Si ya nadie lee la tabla, lo correcto es dropearla y
# sacarla también de _MERGE_*, no dejarla aquí.
_SIN_MODELO_ORM = {
    # `garantias`: modelo/schemas/router eliminados el 2026-08-11 (commit 1923498)
    # al retirar la vista "Registros". En producción la tabla sigue viva (la creó
    # `create_all` cuando el modelo existía, y ningún upgrade la dropea) -> sus
    # filas siguen colgando de proyecto_id. OJO: en un entorno NUEVO ya no la crea
    # `create_all`; depende de que 008_garantias aplique.
    "garantias",
}

_VERSIONS = os.path.join(os.path.dirname(__file__), "..", "..", "alembic", "versions")


def _bloque_create_table(src, tabla):
    """Texto del `create_table(...)` de `tabla` en `src`, o None si no está.

    Balancea paréntesis ignorando los que viven dentro de un string (p. ej. un
    `comment="algo (parcial"`), que si no desalinearían el conteo.
    """
    m = re.search(rf'create_table\(\s*["\']{re.escape(tabla)}["\']', src)
    if not m:
        return None
    i = src.index("(", m.start())  # paréntesis de create_table(
    nivel, cita = 0, None
    j = i
    while j < len(src):
        c = src[j]
        if cita:
            if c == "\\":
                j += 2
                continue
            if c == cita:
                cita = None
        elif c in "\"'":
            cita = c
        elif c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
            if nivel == 0:
                return src[i : j + 1]
        j += 1
    raise AssertionError(f"create_table('{tabla}') sin cerrar")


def _cols_desde_migraciones(tabla):
    """Columnas con las que Alembic deja `tabla` (None si ninguna migración la crea).

    Aplica, en orden de nombre de archivo (que hoy coincide con el orden de la
    cadena por el prefijo numérico, pero NO es lo mismo que seguir down_revision):
    el `create_table` y luego los `add_column`/`drop_column` posteriores.

    Revienta si algún `upgrade()` dropea o renombra la tabla: en ese caso ya no
    existe con ese nombre y tenerla en _MERGE_* rompería la fusión en producción.
    """
    cols = None
    t = re.escape(tabla)
    for nombre in sorted(os.listdir(_VERSIONS)):
        if not nombre.endswith(".py"):
            continue
        with open(os.path.join(_VERSIONS, nombre), encoding="utf-8") as fh:
            # solo el upgrade: el drop_table del downgrade es normal y esperado
            up = fh.read().split("def downgrade", 1)[0]
        for patron, que in (
            (rf'drop_table\(\s*["\']{t}["\']', "dropea"),
            (rf'rename_table\(\s*["\']{t}["\']', "renombra"),
            (rf'DROP\s+TABLE\s+(IF\s+EXISTS\s+)?{t}\b', "dropea (SQL crudo)"),
        ):
            assert not re.search(patron, up, re.I | re.S), (
                f"{nombre} {que} '{tabla}' en upgrade(): ya no existe con ese nombre, "
                f"sacarla de _MERGE_SIMPLE y de _SIN_MODELO_ORM (o renombrarla en ambos)"
            )
        bloque = _bloque_create_table(up, tabla)
        if bloque:
            cols = set(re.findall(r'Column\(\s*["\'](\w+)["\']', bloque))
        if cols is not None:
            cols |= set(re.findall(rf'add_column\(\s*["\']{t}["\']\s*,\s*sa\.Column\(\s*["\'](\w+)["\']', up))
            cols -= set(re.findall(rf'drop_column\(\s*["\']{t}["\']\s*,\s*["\'](\w+)["\']', up))
    return cols


def test_config_referencia_tablas_y_columnas_reales():
    tablas = Base.metadata.tables

    # Anti-podredumbre: si alguien le devuelve el modelo ORM a una de estas, hay
    # que sacarla del set para que vuelva a validarse contra el ORM (más estricto).
    for t in _SIN_MODELO_ORM:
        assert t not in tablas, (
            f"'{t}' ya tiene modelo ORM: quitarla de _SIN_MODELO_ORM"
        )

    def cols(t):
        if t in _SIN_MODELO_ORM:
            c = _cols_desde_migraciones(t)
            assert c, (
                f"'{t}' no tiene modelo ORM y ninguna migración la crea: confirma "
                f"que existe en la base y en qué migración, o sácala de _MERGE_* "
                f"y de _SIN_MODELO_ORM"
            )
            return c
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
