"""El hook `do_orm_execute`: los UPDATE/DELETE masivos dejan de ser invisibles.

Un `UPDATE ... WHERE` no crea objetos en `session.dirty`, así que `before_flush`
--y con él toda la auditoría-- no se entera. `tipo_migration` reescribió 5.086
fallas en 23 arranques sin dejar una fila en `audit_log`, y lo descubrimos por
casualidad.

El banco de pruebas son los patrones reales del inventario de
`tests/escrituras_masivas.py`: los 34 `Query.update/delete`, los 4 del estilo
2.0 y los 32 de `text()` crudo. Los dos primeros grupos tienen que quedar
cubiertos; el tercero **no puede** quedarlo, y eso también se prueba, porque una
cobertura que se cree completa es peor que una que sabe dónde termina.
"""
import json

import pytest
from sqlalchemy import (Column, Integer, String, create_engine, delete, event,
                        text, update)
from sqlalchemy.orm import Session, declarative_base

from app.services import audit
from audit_sqlite import crear_audit_log

Base = declarative_base()


class Falla(Base):
    """Vale por cualquier tabla auditada; `fallas` es la del bug real."""
    __tablename__ = "fallas"
    id = Column(Integer, primary_key=True)
    tipo_id = Column(Integer)
    nota = Column(String)


class Aparte(Base):
    """Una tabla que NO está en `_AUDITED_TABLES`."""
    __tablename__ = "arr_documento"
    id = Column(Integer, primary_key=True)
    v = Column(String)


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    crear_audit_log(engine)

    # Se engancha sobre la clase Session, así que hay que desengancharlo al
    # terminar: si no, queda activo para el resto de la suite y cualquier test
    # que haga un update masivo sobre una tabla auditada se lleva el ruido.
    listener = audit.init_audit_masivo()

    sesion = Session(engine)
    sesion.add_all([Falla(id=i, tipo_id=27, nota="x") for i in range(1, 6)])
    sesion.add(Aparte(id=1, v="a"))
    sesion.commit()
    yield sesion
    sesion.close()
    event.remove(Session, "do_orm_execute", listener)


def _masivas(db):
    filas = db.execute(text(
        "SELECT tabla, accion, registro_id, cambios FROM audit_log")).mappings().all()
    return [dict(f) | {"cambios": json.loads(f["cambios"])} for f in filas
            if json.loads(f["cambios"] or "{}").get("masiva")]


# ── Los dos patrones que el ORM compila: cubiertos ───────────────────────────

def test_query_update_legacy_deja_una_fila_resumen(db):
    """El patrón de `tipo_migration`, con 34 sitios en el inventario."""
    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    filas = _masivas(db)
    assert len(filas) == 1
    assert filas[0]["tabla"] == "fallas" and filas[0]["accion"] == "UPDATE"
    assert filas[0]["cambios"]["filas_afectadas"] == 5


def test_query_delete_legacy_queda_registrado(db):
    db.query(Falla).filter(Falla.id <= 3).delete()

    filas = _masivas(db)
    assert len(filas) == 1 and filas[0]["accion"] == "DELETE"
    assert filas[0]["cambios"]["filas_afectadas"] == 3


def test_el_estilo_2_0_tambien(db):
    """Los 4 sitios de `db.execute(update(X)...)` en `facturacion.py`."""
    db.execute(update(Falla).where(Falla.id == 1).values(nota="z"))

    assert len(_masivas(db)) == 1


def test_el_delete_del_estilo_2_0_tambien(db):
    db.execute(delete(Falla).where(Falla.id == 1))

    assert len(_masivas(db)) == 1


def test_guarda_la_sentencia_para_saber_que_corrio(db):
    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    sentencia = _masivas(db)[0]["cambios"]["sentencia"]
    assert "UPDATE fallas" in sentencia and "tipo_id" in sentencia


def test_registro_id_va_en_cero_porque_no_hay_una_fila(db):
    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    assert _masivas(db)[0]["registro_id"] == 0


def test_atribuye_a_quien_la_corrio(db):
    audit.set_audit_user(9, "Juan Jose", db)

    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    fila = db.execute(text(
        "SELECT usuario_nombre FROM audit_log")).mappings().first()
    assert fila["usuario_nombre"] == "Juan Jose"


def test_la_escritura_ocurre_igual(db):
    """Lo primero que no puede romperse: el hook intercepta la ejecución."""
    n = db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    assert n == 5
    assert db.query(Falla).filter(Falla.tipo_id == 129).count() == 5


# ── Los límites, probados a propósito ────────────────────────────────────────

def test_el_sql_crudo_NO_queda_cubierto(db):
    """El límite grande: 32 sitios del inventario, y no hay forma de cubrirlos.

    Para un `text()`, SQLAlchemy no sabe si es un UPDATE ni sobre qué tabla cae.
    Si algún día esto empieza a fallar es que el hook cambió de alcance, y hay
    que actualizar la documentación antes que el test.
    """
    db.execute(text("UPDATE fallas SET tipo_id = 129 WHERE tipo_id = 27"))

    assert _masivas(db) == []


def test_una_tabla_no_auditada_no_genera_ruido(db):
    db.query(Aparte).filter(Aparte.id == 1).update({"v": "z"})

    assert _masivas(db) == []


def test_un_select_no_genera_nada(db):
    db.query(Falla).filter(Falla.tipo_id == 27).all()

    assert _masivas(db) == []


def test_las_escrituras_por_objeto_no_pasan_por_aca(db):
    """Esas ya las cubre `before_flush`; duplicarlas sería peor que no tenerlas."""
    falla = db.get(Falla, 1)
    falla.nota = "editada"
    db.commit()

    assert _masivas(db) == []


def test_una_fila_resumen_por_sentencia_no_una_por_registro(db):
    """5 filas afectadas, 1 fila de auditoría. Es lo que hace viable auditar
    `panel_contable_linea`, donde un recálculo toca miles."""
    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})

    assert len(_masivas(db)) == 1
    assert _masivas(db)[0]["cambios"]["filas_afectadas"] == 5


def test_el_registro_muere_con_la_transaccion(db):
    db.query(Falla).filter(Falla.tipo_id == 27).update({"tipo_id": 129})
    db.rollback()

    assert _masivas(db) == []
