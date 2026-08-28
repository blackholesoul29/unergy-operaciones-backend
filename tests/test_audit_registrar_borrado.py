"""`registrar_borrado()`: el rastro de lo que se borró sin pasar por el ORM.

Hasta el 2026-08-27, fusionar dos plantas hacía `DELETE FROM proyectos` con SQL
crudo y **no dejaba ni una fila en `audit_log`**: la operación más destructiva
de la app era la única sin rastro. Lo mismo el merge de clientes, con borrado
lógico.

Lo que estos tests fijan, y que un hook genérico sobre `do_orm_execute` no
podría dar nunca: que quede guardado **qué** se borró, no sólo que se borraron
N filas.
"""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import audit
from audit_sqlite import crear_audit_log


@pytest.fixture
def db():
    """Una base mínima con la forma de `audit_log` y una tabla que borrar."""
    engine = create_engine("sqlite:///:memory:")
    crear_audit_log(engine)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE proyectos (
                id INTEGER PRIMARY KEY, nombre_comercial TEXT,
                potencia_instalada_kwp REAL, municipio TEXT)"""))
        conn.execute(text(
            "INSERT INTO proyectos VALUES (7, 'MiniGranja 0007', 300.5, 'Sabana')"))
    sesion = Session(engine)
    yield sesion
    sesion.close()


def _filas_audit(db):
    return [dict(r) for r in db.execute(
        text("SELECT * FROM audit_log")).mappings().all()]


def test_guarda_la_fila_entera_antes_de_que_desaparezca(db):
    audit.registrar_borrado(db, "proyectos", 7)

    fila = _filas_audit(db)[0]
    cambios = json.loads(fila["cambios"])

    assert fila["tabla"] == "proyectos" and fila["registro_id"] == 7
    assert fila["accion"] == "DELETE"
    assert cambios["snapshot"] == {
        "id": 7, "nombre_comercial": "MiniGranja 0007",
        "potencia_instalada_kwp": 300.5, "municipio": "Sabana",
    }


def test_el_snapshot_no_enumera_columnas_a_mano(db):
    """Una columna nueva entra sola. Upstream borra y agrega columnas de
    `proyectos` todas las semanas: una lista escrita a mano queda vieja."""
    db.execute(text("ALTER TABLE proyectos ADD COLUMN codigo_nuevo TEXT"))
    db.execute(text("UPDATE proyectos SET codigo_nuevo = 'ABC' WHERE id = 7"))

    audit.registrar_borrado(db, "proyectos", 7)

    cambios = json.loads(_filas_audit(db)[0]["cambios"])
    assert cambios["snapshot"]["codigo_nuevo"] == "ABC"


def test_el_contexto_del_merge_viaja_con_el_borrado(db):
    """Lo que `merge_proyectos` ya calculó -- movimientos, colisiones, campos
    copiados -- no se tira: es la mitad de la historia del borrado."""
    contexto = {
        "operacion": "merge_proyectos",
        "ganador_id": 3,
        "movimientos": [{"tabla": "fallas", "a_mover": 12, "descartadas_por_colision": 1}],
        "total_filas_movidas": 12,
    }

    audit.registrar_borrado(db, "proyectos", 7, contexto=contexto)

    cambios = json.loads(_filas_audit(db)[0]["cambios"])
    assert cambios["contexto"] == contexto
    assert cambios["snapshot"]["nombre_comercial"] == "MiniGranja 0007"


@pytest.mark.parametrize("tipo", ["hard", "soft"])
def test_distingue_el_borrado_fisico_del_logico(db, tipo):
    """Proyectos se borra de verdad; clientes se da de baja. No es lo mismo."""
    audit.registrar_borrado(db, "proyectos", 7, tipo=tipo)

    assert json.loads(_filas_audit(db)[0]["cambios"])["tipo_borrado"] == tipo


def test_atribuye_a_quien_lo_hizo(db):
    audit.set_audit_user(9, "Juan Jose", db)

    audit.registrar_borrado(db, "proyectos", 7)

    fila = _filas_audit(db)[0]
    assert fila["usuario_id"] == 9 and fila["usuario_nombre"] == "Juan Jose"


def test_si_la_fila_no_existe_no_inventa_nada(db):
    assert audit.registrar_borrado(db, "proyectos", 999) is False
    assert _filas_audit(db) == []


def test_rechaza_un_nombre_de_tabla_que_no_es_un_identificador(db):
    """El nombre se interpola en el SQL. Hoy sólo lo llaman con literales, pero
    eso es una propiedad de los llamadores, no del helper."""
    with pytest.raises(ValueError):
        audit.registrar_borrado(db, "proyectos; DROP TABLE audit_log", 7)


def test_el_registro_muere_con_la_transaccion(db):
    """Si la fusión revienta y hace rollback, el borrado no ocurrió y su
    constancia tampoco debe quedar."""
    audit.registrar_borrado(db, "proyectos", 7)
    db.rollback()

    assert _filas_audit(db) == []


# ── Los dos endpoints que lo usan ────────────────────────────────────────────

def test_los_dos_merges_lo_llaman_antes_de_tocar_al_perdedor():
    """El orden es la única forma de que el retrato salga completo: los dos
    merges vacían campos del perdedor antes de borrarlo."""
    import inspect

    from app.api.v1 import clientes as api_clientes
    from app.api.v1 import proyectos as api_proyectos

    for modulo, tabla in ((api_proyectos, "proyectos"), (api_clientes, "clientes")):
        fuente = inspect.getsource(modulo)
        i = fuente.index(f'registrar_borrado(db, "{tabla}"')
        j = fuente.index(f"UPDATE {tabla} SET {{f}}=NULL WHERE id=:loser")
        assert i < j, f"{tabla}: el retrato se toma después de vaciar campos"
