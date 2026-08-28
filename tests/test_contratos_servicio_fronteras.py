"""ContratoServicio <-> Frontera (muchos-a-muchos), tabla contrato_frontera.

Item 4 del diagnostico de integridad de Fronteras, 2026-08-25:
ContratoServicio.proyecto_id vincula un contrato a un Proyecto completo,
pero una planta puede tener varias Fronteras (generacion, consumo,
distintos medidores) y dos contratos sobre la misma planta (ej. Operacion
y Representacion) a veces aplican a puntos de medida distintos -- no
habia forma de expresarlo antes de esto."""
import pytest
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.models.contratos import ContratoServicio
from app.schemas.contratos_servicio import ContratoServicioCreate, ContratoServicioUpdate
from app.api.v1 import contratos_servicio as api
from fastapi import HTTPException


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


ADMIN = None
_next_id = iter(range(1, 100000))


def _proyecto(db, **kw):
    kw.setdefault("id", next(_next_id))
    kw.setdefault("nombre_comercial", "Proyecto de prueba")
    p = Proyecto(**kw)
    db.add(p)
    db.flush()
    return p


def _frontera(db, proyecto_id, **kw):
    kw.setdefault("id", next(_next_id))
    kw.setdefault("nombre_frontera", "Frontera de prueba")
    kw.setdefault("codigo_frontera", f"frt{kw['id']:05d}")
    kw.setdefault("tipo_frontera", "generacion")
    kw.setdefault("estado", "activa")
    f = Frontera(proyecto_id=proyecto_id, **kw)
    db.add(f)
    db.flush()
    return f


def test_crear_contrato_con_frontera_ids_las_vincula(db):
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    f2 = _frontera(db, proy.id)

    body = ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento",
                                   frontera_ids=[f1.id, f2.id])
    out = api.create_contrato(body, db=db, _=ADMIN)

    assert {f.id for f in out.fronteras} == {f1.id, f2.id}


def test_crear_contrato_sin_frontera_ids_no_vincula_nada(db):
    proy = _proyecto(db)
    out = api.create_contrato(
        ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento"),
        db=db, _=ADMIN,
    )
    assert out.fronteras == []


def test_editar_agrega_y_quita_fronteras(db):
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    f2 = _frontera(db, proy.id)
    f3 = _frontera(db, proy.id)

    contrato = api.create_contrato(
        ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )

    out = api.update_contrato(
        contrato.id, ContratoServicioUpdate(frontera_ids=[f2.id, f3.id]), db=db, _=ADMIN,
    )
    assert {f.id for f in out.fronteras} == {f2.id, f3.id}


def test_editar_sin_tocar_frontera_ids_deja_los_vinculos_intactos(db):
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    contrato = api.create_contrato(
        ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )

    # No se manda frontera_ids -- None por defecto en ContratoServicioUpdate,
    # exclude_unset lo deja fuera del payload, no debe tocar los vinculos.
    out = api.update_contrato(
        contrato.id, ContratoServicioUpdate(estado="terminado"), db=db, _=ADMIN,
    )
    assert {f.id for f in out.fronteras} == {f1.id}


def test_editar_con_lista_vacia_desvincula_todas(db):
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    contrato = api.create_contrato(
        ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )

    out = api.update_contrato(contrato.id, ContratoServicioUpdate(frontera_ids=[]), db=db, _=ADMIN)
    assert out.fronteras == []


def test_ids_repetidos_colapsan_sin_violar_el_unique(db):
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    out = api.create_contrato(
        ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento",
                                frontera_ids=[f1.id, f1.id, f1.id]),
        db=db, _=ADMIN,
    )
    assert [f.id for f in out.fronteras] == [f1.id]


def test_frontera_inexistente_da_400(db):
    proy = _proyecto(db)
    with pytest.raises(HTTPException) as exc:
        api.create_contrato(
            ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[999999]),
            db=db, _=ADMIN,
        )
    assert exc.value.status_code == 400


def test_frontera_borrada_da_400(db):
    import datetime as dt
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id, deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.create_contrato(
            ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[f1.id]),
            db=db, _=ADMIN,
        )
    assert exc.value.status_code == 400


def test_frontera_de_otro_proyecto_da_400(db):
    proy_a = _proyecto(db, nombre_comercial="Planta A")
    proy_b = _proyecto(db, nombre_comercial="Planta B")
    f_de_b = _frontera(db, proy_b.id)

    with pytest.raises(HTTPException) as exc:
        api.create_contrato(
            ContratoServicioCreate(proyecto_id=proy_a.id, servicio_aplica="mantenimiento", frontera_ids=[f_de_b.id]),
            db=db, _=ADMIN,
        )
    assert exc.value.status_code == 400
    assert "no pertenecen al proyecto" in exc.value.detail


def test_contrato_sin_proyecto_no_valida_pertenencia(db):
    """Un contrato de tipo 'internet' u otro sin proyecto_id no tiene con
    que comparar -- no se bloquea la vinculacion en ese caso."""
    proy = _proyecto(db)
    f1 = _frontera(db, proy.id)
    out = api.create_contrato(
        ContratoServicioCreate(servicio_aplica="internet", frontera_ids=[f1.id]),
        db=db, _=ADMIN,
    )
    assert [f.id for f in out.fronteras] == [f1.id]


def test_get_no_dispara_una_query_por_frontera(db):
    """selectinload(ContratoServicio.fronteras) en _load_options evita N+1
    al listar varios contratos con fronteras vinculadas."""
    proy = _proyecto(db)
    for _ in range(3):
        f = _frontera(db, proy.id)
        api.create_contrato(
            ContratoServicioCreate(proyecto_id=proy.id, servicio_aplica="mantenimiento", frontera_ids=[f.id]),
            db=db, _=ADMIN,
        )

    contador = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*a, **kw):
        contador["n"] += 1

    resultado = api.list_contratos(tipo=None, proyecto_id=None, codigo_tsf=None, limit=100, db=db, _=ADMIN)

    assert len(resultado) == 3
    # 1 query para los contratos + un puñado fijo de selectinload (contratante/
    # prestador/proyecto/fronteras) -- no debe crecer con la cantidad de filas.
    assert contador["n"] < 10, f"{contador['n']} queries para 3 contratos -- posible N+1"
