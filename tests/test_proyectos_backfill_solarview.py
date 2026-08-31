"""project_id_solarview no tenia ningun mecanismo de escritura automatica (a
diferencia de project_id_solenium) -- se emparejaba a mano por SQL directo.
Este backfill empareja por nombre contra SolarViewClient.get_company_projects(),
mismo criterio que proyectos_backfill_solenium.py."""
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.proyectos import Proyecto


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"
from app.services import proyectos_backfill_solarview as backfill_mod
from app.services.proyectos_backfill_solarview import (
    backfill_project_id_solarview,
    sincronizar_project_id_solarview_si_aplica,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class _ClienteFalso:
    def __init__(self, projects):
        self._projects = projects
        self.enabled = True

    def get_company_projects(self):
        return self._projects


def _mockear_cliente(monkeypatch, projects, enabled=True):
    cliente = _ClienteFalso(projects)
    cliente.enabled = enabled
    monkeypatch.setattr(backfill_mod, "SolarViewClient", lambda: cliente)
    return cliente


def _proyecto(db, nombre, project_id_solarview=None):
    p = Proyecto(nombre_comercial=nombre, project_id_solarview=project_id_solarview)
    db.add(p)
    db.commit()
    return p


PROYECTOS_SOLARVIEW = [
    {"id": 103, "name": "Minigranja Solar El Prado"},
    {"id": 8, "name": "Minigranja Solar La Esperanza"},
]


def test_dry_run_no_persiste(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "Minigranja Solar El Prado")

    res = backfill_project_id_solarview(db, apply=False)

    assert res["ok"] is True
    assert len(res["asignados"]) == 1
    assert res["asignados"][0]["cambios"]["proyecto.project_id_solarview"] == "103"
    db.refresh(p)
    assert p.project_id_solarview is None


def test_apply_persiste_el_match(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "Minigranja Solar El Prado")

    res = backfill_project_id_solarview(db, apply=True)

    assert len(res["asignados"]) == 1
    db.refresh(p)
    assert p.project_id_solarview == "103"


def test_nunca_sobreescribe_valor_ya_cargado(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "MGS 0001 - El Prado", project_id_solarview="999")

    res = backfill_project_id_solarview(db, apply=True)

    assert res["revisados"] == 0  # ni siquiera entra al query -- ya tenia valor
    db.refresh(p)
    assert p.project_id_solarview == "999"


def test_sin_match_seguro_queda_reportado(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "Proyecto totalmente distinto sin relacion")

    res = backfill_project_id_solarview(db, apply=True)

    assert res["asignados"] == []
    assert len(res["sin_match_seguro"]) == 1
    db.refresh(p)
    assert p.project_id_solarview is None


def test_dos_proyectos_mismo_match_solo_el_primero_se_queda(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p1 = _proyecto(db, "Minigranja Solar El Prado")
    p2 = _proyecto(db, "Minigranja Solar El Prado")  # duplicado real, mismo nombre

    res = backfill_project_id_solarview(db, apply=True)

    asignados_ids = {a["proyecto_id"] for a in res["asignados"]}
    assert asignados_ids == {p1.id}
    assert len(res["sin_match_seguro"]) == 1
    db.refresh(p2)
    assert p2.project_id_solarview is None


def test_sin_credenciales_retorna_error(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW, enabled=False)
    _proyecto(db, "MGS 0001 - El Prado")

    res = backfill_project_id_solarview(db, apply=True)

    assert res["ok"] is False
    assert "Credenciales" in res["error"]


def test_sincronizar_si_aplica_asigna_un_solo_proyecto(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "Minigranja Solar El Prado")

    resultado = sincronizar_project_id_solarview_si_aplica(p, db)

    assert resultado == "103"
    db.refresh(p)
    assert p.project_id_solarview == "103"


def test_sincronizar_si_aplica_no_hace_nada_si_ya_tiene_valor(db, monkeypatch):
    cliente = _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    p = _proyecto(db, "MGS 0001 - El Prado", project_id_solarview="777")

    resultado = sincronizar_project_id_solarview_si_aplica(p, db)

    assert resultado is None
    db.refresh(p)
    assert p.project_id_solarview == "777"


def test_sincronizar_si_aplica_respeta_conflicto_de_unicidad(db, monkeypatch):
    _mockear_cliente(monkeypatch, PROYECTOS_SOLARVIEW)
    _proyecto(db, "Minigranja Solar El Prado", project_id_solarview="103")
    p2 = _proyecto(db, "Minigranja Solar El Prado")  # matchearia al mismo id=103, ya tomado

    resultado = sincronizar_project_id_solarview_si_aplica(p2, db)

    assert resultado is None
    db.refresh(p2)
    assert p2.project_id_solarview is None
