"""Empresa responsable por PPA + exclusión de la Matriz anual.

Motivación: en /mem/cumplimiento aparecían contratos que gestiona un tercero
(BIA*, Sol&Cielo*) y ensuciaban la Matriz anual. El responsable es un catálogo
—no texto libre— para que los filtros de la plataforma trabajen sobre valores
consistentes, y la bandera `incluir_en_cumplimiento` es lo que esconde el
contrato.

Reglas que se fijan aquí:
  - contrato SIN responsable → SIEMPRE se incluye (nada se esconde por omisión)
  - solo_relevantes=False (default) → no cambia el universo de las demás vistas
  - la clasificación inicial es one-shot: no revierte cambios manuales
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import PPAContrato, PPAResponsable
from app.schemas.ppa import PPAResponsableIn, PPAResponsableUpdate, PPAResponsableAsignar
from app.api.v1 import cumplimiento as cumpl_api
from app.api.v1 import ppa as ppa_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    """SQLite solo autoincrementa un PK declarado INTEGER; con BIGINT (lo que
    rinde BigInteger) el insert sin id revienta. En Postgres el PK es BIGSERIAL,
    así que esto es puro andamiaje de test."""
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine, tables=[PPAContrato.__table__, PPAResponsable.__table__]
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _resp(db, nombre, incluir=True):
    r = PPAResponsable(id=next(_ids), nombre=nombre, incluir_en_cumplimiento=incluir)
    db.add(r)
    db.flush()
    return r


def _contrato(db, nombre, responsable=None, tipo="venta", codigo=None):
    c = PPAContrato(
        id=next(_ids), nombre_interno=nombre, numero_codigo_contrato=codigo,
        tipo_contrato=tipo, responsable_id=responsable.id if responsable else None,
        fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
    )
    db.add(c)
    db.flush()
    return c


# ── Filtro de la Matriz anual ────────────────────────────────────────────────

def test_solo_relevantes_excluye_los_marcados_y_conserva_el_resto(db):
    unergy = _resp(db, "Unergy", incluir=True)
    externo = _resp(db, "Externo", incluir=False)
    _contrato(db, "Terpel 8", responsable=unergy)
    _contrato(db, "BIA Naos 1", responsable=externo)
    _contrato(db, "Sin clasificar", responsable=None)
    db.commit()

    nombres = {c.nombre_interno for c in
               cumpl_api._query_contratos_venta(db, 2026, solo_relevantes=True)}
    assert nombres == {"Terpel 8", "Sin clasificar"}


def test_el_filtro_es_el_default_en_todo_el_router(db):
    """Todas las vistas de /mem/cumplimiento ocultan los no relevantes, así que
    el default de los dos helpers es filtrar."""
    externo = _resp(db, "Externo", incluir=False)
    _contrato(db, "BIA Naos 1", responsable=externo)
    _contrato(db, "Terpel 8")
    db.commit()

    assert [c.nombre_interno for c in cumpl_api._query_contratos_venta(db, 2026)] == ["Terpel 8"]
    assert [c.nombre_interno for c in cumpl_api._contratos_vigentes(db, 2026)] == ["Terpel 8"]


def test_incluir_todos_los_trae_de_vuelta(db):
    externo = _resp(db, "Externo", incluir=False)
    _contrato(db, "BIA Naos 1", responsable=externo)
    _contrato(db, "Terpel 8")
    db.commit()

    todos = cumpl_api._contratos_vigentes(db, 2026, solo_relevantes=False)
    assert {c.nombre_interno for c in todos} == {"BIA Naos 1", "Terpel 8"}


def test_sin_responsables_ocultos_no_se_agrega_filtro(db):
    """Si nadie está marcado como no relevante, la consulta no cambia."""
    _resp(db, "Unergy", incluir=True)
    _contrato(db, "Terpel 8")
    db.commit()

    assert cumpl_api._filtro_responsable_relevante(db) is None
    assert len(cumpl_api._contratos_vigentes(db, 2026)) == 1


def test_sigue_excluyendo_contratos_de_compra(db):
    unergy = _resp(db, "Unergy", incluir=True)
    _contrato(db, "Compra NAOS 1", responsable=unergy, tipo="compra")
    _contrato(db, "Terpel 8", responsable=unergy)
    db.commit()

    nombres = {c.nombre_interno for c in
               cumpl_api._query_contratos_venta(db, 2026, solo_relevantes=True)}
    assert nombres == {"Terpel 8"}


def test_cerrar_periodo_y_descubrimientos_no_filtran(db):
    """Son los dos call sites que pasan solo_relevantes=False a propósito:
    cerrar-periodo PERSISTE el cierre mensual (dejar contratos fuera cambiaría el
    histórico guardado) y descubrimientos existe para destapar exposición.
    Este test los ancla leyendo el código: si alguien quita el parámetro, falla."""
    import inspect
    fuente = inspect.getsource(cumpl_api)
    assert fuente.count("solo_relevantes=False") == 2

    for fn in (cumpl_api.get_descubrimientos, cumpl_api.cerrar_periodo):
        assert "incluir_todos" not in inspect.signature(fn).parameters


def test_payload_de_fila_expone_el_responsable(db):
    externo = _resp(db, "Externo", incluir=False)
    c = _contrato(db, "BIA Naos 1", responsable=externo)
    sin = _contrato(db, "Sin clasificar", responsable=None)
    db.commit()

    assert cumpl_api._responsable_payload(c) == {
        "responsable_id": externo.id, "responsable": "Externo",
        "responsable_relevante": False,
    }
    # sin responsable → relevante por defecto, para que la UI no lo pinte como oculto
    assert cumpl_api._responsable_payload(sin)["responsable_relevante"] is True


# ── Clasificación inicial (seed de arranque) ─────────────────────────────────

def test_seed_clasifica_externos_por_nombre_y_el_resto_a_unergy(db):
    _contrato(db, "BIA Naos 1")
    _contrato(db, "BIA Polaris 1")
    _contrato(db, "Sol&Cielo7")
    _contrato(db, "Terpel 8")
    db.commit()

    rep = ppa_api.sembrar_responsables_ppa(db)

    assert rep["externo"] == 3
    assert rep["unergy"] == 1
    assert sorted(rep["sin_match"]) == ["BIA Delta 1", "BIA Naos 2", "BIA Naos 3", "Sol&Cielo9"]
    externo = db.query(PPAResponsable).filter_by(nombre="Externo").one()
    assert externo.incluir_en_cumplimiento is False
    ocultos = {c.nombre_interno for c in db.query(PPAContrato)
               .filter(PPAContrato.responsable_id == externo.id)}
    assert ocultos == {"BIA Naos 1", "BIA Polaris 1", "Sol&Cielo7"}


def test_seed_tolera_mayusculas_espacios_y_tildes(db):
    _contrato(db, "  bia   naos 1 ")
    _contrato(db, "SOL & CIELO 9")
    db.commit()

    ppa_api.sembrar_responsables_ppa(db)

    externo = db.query(PPAResponsable).filter_by(nombre="Externo").one()
    assert db.query(PPAContrato).filter(PPAContrato.responsable_id == externo.id).count() == 2


def test_seed_es_one_shot_no_revierte_cambios_manuales(db):
    """Un redeploy no debe deshacer una reclasificación hecha en la UI."""
    _contrato(db, "BIA Naos 1")
    _contrato(db, "Terpel 8")
    db.commit()
    ppa_api.sembrar_responsables_ppa(db)

    unergy = db.query(PPAResponsable).filter_by(nombre="Unergy").one()
    bia = db.query(PPAContrato).filter_by(nombre_interno="BIA Naos 1").one()
    bia.responsable_id = unergy.id   # Juan lo corrige a mano
    db.commit()

    rep = ppa_api.sembrar_responsables_ppa(db)   # siguiente arranque

    assert rep["clasifico"] is False
    db.refresh(bia)
    assert bia.responsable_id == unergy.id


def test_seed_no_duplica_el_catalogo(db):
    ppa_api.sembrar_responsables_ppa(db)
    ppa_api.sembrar_responsables_ppa(db)
    assert db.query(PPAResponsable).count() == 2


def test_seed_ignora_contratos_borrados(db):
    from datetime import datetime, timezone
    c = _contrato(db, "BIA Naos 1")
    c.deleted_at = datetime.now(timezone.utc)
    db.commit()

    rep = ppa_api.sembrar_responsables_ppa(db)

    assert rep["externo"] == 0
    assert c.responsable_id is None


# ── CRUD del catálogo (endpoints llamados como funciones) ────────────────────

def test_listar_incluye_el_conteo_de_contratos(db):
    unergy = _resp(db, "Unergy")
    _resp(db, "Externo", incluir=False)
    _contrato(db, "Terpel 8", responsable=unergy)
    _contrato(db, "Terpel 1", responsable=unergy)
    db.commit()

    por_nombre = {r.nombre: r for r in ppa_api.list_responsables(db=db, _=None)}
    assert por_nombre["Unergy"].n_contratos == 2
    assert por_nombre["Externo"].n_contratos == 0


def test_crear_con_nombre_repetido_da_409_sin_importar_mayusculas(db):
    ppa_api.create_responsable(PPAResponsableIn(nombre="Unergy"), db=db, _=None)
    with pytest.raises(HTTPException) as exc:
        ppa_api.create_responsable(PPAResponsableIn(nombre="  unergy "), db=db, _=None)
    assert exc.value.status_code == 409


def test_renombrar_no_choca_consigo_mismo(db):
    r = ppa_api.create_responsable(PPAResponsableIn(nombre="Externo"), db=db, _=None)
    out = ppa_api.update_responsable(r.id, PPAResponsableUpdate(nombre="Externo"), db=db, _=None)
    assert out.nombre == "Externo"


def test_marcar_no_relevante_lo_saca_de_la_matriz(db):
    r = ppa_api.create_responsable(PPAResponsableIn(nombre="BIA"), db=db, _=None)
    _contrato(db, "BIA Naos 1", responsable=db.get(PPAResponsable, r.id))
    db.commit()
    assert len(cumpl_api._query_contratos_venta(db, 2026, solo_relevantes=True)) == 1

    ppa_api.update_responsable(r.id, PPAResponsableUpdate(incluir_en_cumplimiento=False), db=db, _=None)

    assert cumpl_api._query_contratos_venta(db, 2026, solo_relevantes=True) == []


def test_no_se_puede_borrar_un_responsable_con_contratos(db):
    """Borrar haría SET NULL y los contratos reaparecerían en la matriz sin aviso."""
    r = _resp(db, "BIA", incluir=False)
    _contrato(db, "BIA Naos 1", responsable=r)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        ppa_api.delete_responsable(r.id, db=db, _=None)
    assert exc.value.status_code == 409

    ppa_api.asignar_responsable(
        PPAResponsableAsignar(contrato_ids=[c.id for c in db.query(PPAContrato)], responsable_id=None),
        db=db, _=None,
    )
    ppa_api.delete_responsable(r.id, db=db, _=None)
    assert db.query(PPAResponsable).count() == 0


def test_asignar_en_bloque(db):
    externo = _resp(db, "Externo", incluir=False)
    a = _contrato(db, "BIA Naos 1")
    b = _contrato(db, "BIA Naos 2")
    c = _contrato(db, "Terpel 8")
    db.commit()

    res = ppa_api.asignar_responsable(
        PPAResponsableAsignar(contrato_ids=[a.id, b.id], responsable_id=externo.id), db=db, _=None
    )

    assert res == {"actualizados": 2}
    assert {x.nombre_interno for x in
            cumpl_api._query_contratos_venta(db, 2026, solo_relevantes=True)} == {"Terpel 8"}


def test_asignar_a_un_responsable_inexistente_da_404(db):
    a = _contrato(db, "Terpel 8")
    db.commit()
    with pytest.raises(HTTPException) as exc:
        ppa_api.asignar_responsable(
            PPAResponsableAsignar(contrato_ids=[a.id], responsable_id=9_999), db=db, _=None
        )
    assert exc.value.status_code == 404
