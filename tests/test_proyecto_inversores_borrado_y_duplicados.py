"""Dos huecos reales encontrados en la auditoría de proyecto_inversores del
2026-08-27, tras eliminar el backfill automático (causa de la condición de
carrera) y agregar UniqueConstraint(proyecto_id, nombre) (migración 112):

1. `FallaInversor.proyecto_inversor_id` documentaba en su propio docstring
   que "puede quedar NULL si el inversor se borra del catálogo", pero el FK
   nunca tuvo `ondelete="SET NULL"` (creado vía create_all, sin migración
   Alembic propia) -- con 4213 filas reales en producción, borrar cualquier
   inversor con al menos una falla histórica asociada reventaba con un
   IntegrityError sin capturar (500) en vez de retirarse limpiamente.
2. `add_inversor`/`update_inversor` no capturaban el IntegrityError del
   UniqueConstraint nuevo -- un doble clic (p. ej. el prefill de inversores
   típicos en FallaForm.vue/FallaCreateSheet.vue) mostraba un 500 crudo de
   Postgres en vez de un mensaje accionable.
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto, ProyectoInversor
from app.models.usuarios import Usuario
from app.models.fallas import Falla, FallaCatEstado, FallaCatPrioridad, FallaInversor
from app.schemas.proyectos import ProyectoInversorCreate, ProyectoInversorUpdate
from app.api.v1 import proyectos as proyectos_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    # SQLite no aplica FKs por defecto -- sin este PRAGMA, ondelete="SET NULL"
    # queda declarado pero nunca se ejecuta, y el test no probaría nada real.
    @event.listens_for(engine, "connect")
    def _fk_on(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto_con_falla_base(db):
    p = Proyecto(id=1, nombre_comercial="Test")
    db.add(p)
    db.add(FallaCatEstado(id=1, codigo="abierta", etiqueta="Abierta", orden=1, es_estado_final=False))
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=3))
    db.add(Usuario(id=1, nombre="Laura", email="laura@unergy.io",
                   password_hash="x", rol="operaciones", activo=True))
    db.commit()
    return p


def test_borrar_un_inversor_con_fallas_historicas_deja_null_no_revienta(db):
    _proyecto_con_falla_base(db)
    inv = ProyectoInversor(proyecto_id=1, nombre="Inversor 1", potencia_nominal_kw=300, activo=True)
    db.add(inv)
    db.commit()

    falla = Falla(codigo_interno="FAL-2026-00001", proyecto_id=1,
                  estado_id=1, prioridad_id=1, registrado_por_id=1,
                  descripcion="no genera", fecha_identificacion=dt.date(2026, 8, 27))
    db.add(falla)
    db.commit()
    fi = FallaInversor(falla_id=falla.id, proyecto_inversor_id=inv.id, nombre="Inversor 1", potencia_kw=300)
    db.add(fi)
    db.commit()

    proyectos_api.delete_inversor(id=1, inv_id=inv.id, db=db, _=None)

    assert db.get(ProyectoInversor, inv.id) is None
    db.refresh(fi)
    assert fi.proyecto_inversor_id is None
    # El snapshot histórico sobrevive intacto -- es lo que documenta conservar.
    assert fi.nombre == "Inversor 1"
    assert float(fi.potencia_kw) == 300


def test_agregar_inversor_con_nombre_duplicado_da_409_no_500(db):
    _proyecto_con_falla_base(db)
    proyectos_api.add_inversor(
        id=1, data=ProyectoInversorCreate(nombre="Inversor 1", potencia_nominal_kw=300), db=db, _=None,
    )

    with pytest.raises(Exception) as exc:
        proyectos_api.add_inversor(
            id=1, data=ProyectoInversorCreate(nombre="Inversor 1", potencia_nominal_kw=300), db=db, _=None,
        )
    assert exc.value.status_code == 409


def test_renombrar_inversor_a_uno_ya_existente_da_409_no_500(db):
    _proyecto_con_falla_base(db)
    proyectos_api.add_inversor(
        id=1, data=ProyectoInversorCreate(nombre="Inversor 1", potencia_nominal_kw=300), db=db, _=None,
    )
    inv2 = proyectos_api.add_inversor(
        id=1, data=ProyectoInversorCreate(nombre="Inversor 2", potencia_nominal_kw=300), db=db, _=None,
    )

    with pytest.raises(Exception) as exc:
        proyectos_api.update_inversor(
            id=1, inv_id=inv2.id, data=ProyectoInversorUpdate(nombre="Inversor 1"), db=db, _=None,
        )
    assert exc.value.status_code == 409
