"""Backfill de operador_red_id desde el texto libre `proyecto.operador_red`
hacia el catalogo `operadores_red` (_backfill_operador_red_info en
app/api/v1/fronteras.py).

Usa el mismo algoritmo de coincidencia difusa (`mejor_candidato`) que ya
protege los avisos de duplicados en Operadores de Red/Proyectos/Fronteras --
por eso variantes de puntuacion o espacios sí matchean (a diferencia del
match exacto de texto normalizado que se usaba antes), sin perder la cautela
de no adivinar entre 2 candidatos ambiguos."""
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.operadores_red import OperadorRed, OperadorRedContacto
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.api.v1.fronteras import _backfill_operador_red_info


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, Frontera.__table__, OperadorRed.__table__,
            OperadorRedContacto.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _operador(db, **kw):
    o = OperadorRed(id=next(_ids), **kw)
    db.add(o)
    db.commit()
    return o


def _proyecto(db, operador_red_texto, operador_red_id=None, fronteras_sin_operador=0):
    p = Proyecto(
        id=next(_ids), nombre_comercial=f"Proyecto {operador_red_texto}",
        operador_red=operador_red_texto, operador_red_id=operador_red_id,
    )
    p.fronteras = [
        Frontera(id=next(_ids), nombre_frontera="F", tipo_frontera="generacion")
        for _ in range(fronteras_sin_operador)
    ]
    db.add(p)
    db.commit()
    return p


def test_variante_de_puntuacion_y_mayusculas_matchea(db):
    op = _operador(db, nombre_legal="Electrificadora del Caribe S.A.S. E.S.P.", nombre_comercial="Afinia")
    p = _proyecto(db, "ELECTRIFICADORA DEL CARIBE SAS ESP")

    resultado = _backfill_operador_red_info(db, dry_run=True)

    assert resultado["actualizados"] == 1
    assert resultado["sin_match"] == 0
    assert resultado["detalle"][0]["id"] == p.id
    assert resultado["detalle"][0]["operador_red_id"] == op.id


def test_nombre_ambiguo_entre_dos_operadores_no_matchea(db):
    _operador(db, nombre_legal="Central Electrica del Norte S.A.")
    _operador(db, nombre_legal="Central Electrica del Sur S.A.")
    _proyecto(db, "Central Electrica")

    resultado = _backfill_operador_red_info(db, dry_run=True)

    assert resultado["actualizados"] == 0
    assert resultado["sin_match"] == 1


def test_proyecto_ya_vinculado_no_se_incluye_como_candidato(db):
    op = _operador(db, nombre_legal="Afinia")
    _proyecto(db, "Afinia", operador_red_id=op.id)

    resultado = _backfill_operador_red_info(db, dry_run=True)

    assert resultado["total_candidatos"] == 0


def test_dry_run_no_escribe_en_bd(db):
    op = _operador(db, nombre_legal="Afinia")
    p = _proyecto(db, "Afinia")

    _backfill_operador_red_info(db, dry_run=True)

    db.refresh(p)
    assert p.operador_red_id is None


def test_dry_run_false_escribe_y_cascada_a_fronteras(db):
    op = _operador(db, nombre_legal="Afinia")
    p = _proyecto(db, "Afinia", fronteras_sin_operador=2)

    _backfill_operador_red_info(db, dry_run=False)

    db.refresh(p)
    assert p.operador_red_id == op.id
    assert all(f.operador_red_id == op.id for f in p.fronteras)
