"""Ocultar los costos en cero.

Más de la mitad de los 10.536 costos valen cero, y es estructural: el reparto le
crea una fila de cada concepto a todos los proyectos, así que uno que no es
comercializador arrastra igual su `iva_comercializador` en cero.

Ocultarlos es lo correcto para leer la tabla, pero es delicado en algo contable:
si una fila no aparece hay que poder distinguir "vale cero" de "no existe". Por
eso `ocultos_en_cero` viaja siempre y se cuenta sobre los demás filtros ya
aplicados, no sobre la tabla entera.
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import liquidaciones_proxy
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.base import Base
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
from app.services import liquidaciones_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Cliente.__table__, Proyecto.__table__])
    s = sessionmaker(bind=engine)()
    s.add(Proyecto(id=1, nombre_comercial="El Molino", sub_project="elmolino"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(liquidaciones_proxy.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id=1)
    return TestClient(app)


TIPOS = [
    {"name": "iva_comercializador", "long_name": "IVA comercializador", "group": "xm"},
    {"name": "energia_bolsa_generador", "long_name": "Energía en bolsa", "group": "xm"},
    {"name": "lease", "long_name": "Arrendamiento", "group": "opex"},
]


def _costo(id_, tipo, valor, desde="2026-07-01", hasta="2026-07-31"):
    return {"id": id_, "project": "elmolino", "payment_type": tipo, "value": valor,
            "from_date": desde, "to_date": hasta, "payment_frecuency": "monthly",
            "version": "txf"}


COSTOS = [
    _costo(1, "energia_bolsa_generador", "1500.00"),
    _costo(2, "iva_comercializador", "0.00"),
    _costo(3, "iva_comercializador", "0"),
    _costo(4, "lease", "0.00"),
    _costo(5, "lease", "900.50"),
    _costo(6, "energia_bolsa_generador", "-320.00"),
]


@pytest.fixture(autouse=True)
def _api(monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_costos", lambda **kw: list(COSTOS))
    monkeypatch.setattr(liquidaciones_api, "listar_catalogos",
                        lambda: {"tipos_costo": list(TIPOS), "empresas": [], "precios_energia": []})


def _get(client, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/api/v1/liquidaciones-api/costos?{q}")
    assert r.status_code == 200, r.text
    return r.json()


def test_por_defecto_oculta_los_ceros(client):
    d = _get(client)
    assert sorted(c["id"] for c in d["results"]) == [1, 5, 6]
    assert d["total"] == 3


def test_siempre_dice_cuantos_ocultó(client):
    """Sin este número, una fila ausente no se distingue de una inexistente."""
    assert _get(client)["ocultos_en_cero"] == 3


def test_el_conteo_de_ocultos_llega_aunque_se_muestren(client):
    d = _get(client, solo_con_valor="false")
    assert d["total"] == 6
    assert d["ocultos_en_cero"] == 3


def test_mostrar_todo_devuelve_los_ceros(client):
    d = _get(client, solo_con_valor="false")
    assert sorted(c["id"] for c in d["results"]) == [1, 2, 3, 4, 5, 6]


def test_un_negativo_no_es_un_cero(client):
    """Las notas crédito llegan en negativo y son plata real."""
    assert 6 in [c["id"] for c in _get(client)["results"]]


def test_el_conteo_respeta_los_demas_filtros(client):
    """«N en cero ocultas» tiene que hablar de lo que se está mirando.

    Filtrando por grupo xm hay dos ceros (los dos `iva_comercializador`), no los
    tres que tiene la tabla entera: el `lease` en cero es de otro grupo.
    """
    d = _get(client, grupo="xm")
    assert d["ocultos_en_cero"] == 2
    assert sorted(c["id"] for c in d["results"]) == [1, 6]


def test_el_conteo_respeta_el_filtro_de_periodo(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_costos", lambda **kw: [
        _costo(10, "lease", "0.00", "2026-07-01", "2026-07-31"),
        _costo(11, "lease", "0.00", "2025-01-01", "2025-01-31"),
    ])
    assert _get(client, anio=2026, mes=7)["ocultos_en_cero"] == 1


def test_un_valor_ilegible_no_se_oculta(client, monkeypatch):
    """Un `value` nulo o corrupto no es un cero: hay que verlo para arreglarlo."""
    monkeypatch.setattr(liquidaciones_api, "listar_costos", lambda **kw: [
        _costo(20, "lease", None),
        _costo(21, "lease", "no-es-un-numero"),
        _costo(22, "lease", "0.00"),
    ])
    d = _get(client)
    assert sorted(c["id"] for c in d["results"]) == [20, 21]
    assert d["ocultos_en_cero"] == 1


def test_la_paginacion_cuenta_solo_lo_visible(client):
    """`total` es lo paginable; si contara los ocultos, la última página saldría vacía."""
    d = _get(client, size=2, page=1)
    assert d["total"] == 3 and len(d["results"]) == 2
    assert len(_get(client, size=2, page=2)["results"]) == 1
