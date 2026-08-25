"""Los tres históricos que expone el proxy: despachos, consumo e IPP.

Lo que se prueba aquí es la traducción, que es donde están las trampas: la API
externa habla de tópicos y de ``con_hourNN``, y en pantalla hay que ver el
nombre de la planta y un total diario que allá no existe.
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
    """`proyectos` tiene columnas JSONB y SQLite no sabe renderizarlas."""
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Cliente.__table__, Proyecto.__table__])
    s = sessionmaker(bind=engine)()
    # La Reserva es el caso incómodo: generación la llama `reserva` y
    # liquidaciones `MGS 0012 La Reserva`, y no se pueden unificar.
    s.add(Proyecto(id=1, nombre_comercial="MGS 0012 La Reserva",
                   sub_project="reserva", topico_liquidaciones="MGS 0012 La Reserva"))
    s.add(Proyecto(id=2, nombre_comercial="El Molino", sub_project="elmolino"))
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


# ── Despachos liquidados ─────────────────────────────────────────────────────

DESPACHOS = [
    {"id": 1, "date": "2026-07-01", "energy": 100.0, "price": 5000.0,
     "data_type": "dispatch", "contract_energy_project": 3, "version": "txf",
     "project": "elmolino", "contract_code": "84962"},
    {"id": 2, "date": "2026-07-31", "energy": 50.0, "price": -900.0,
     "data_type": "purchase", "contract_energy_project": 4, "version": "txf",
     "project": "MGS 0012 La Reserva", "contract_code": "84963"},
    {"id": 3, "date": "2026-07-15", "energy": 7.0, "price": 12.0,
     "data_type": "dispatch", "contract_energy_project": 9, "version": "txf",
     "project": "planta_que_no_esta_en_esta_base", "contract_code": None},
]


def test_despachos_muestran_el_nombre_de_esta_base(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_liquidaciones_mercado",
                        lambda **kw: list(DESPACHOS))
    r = client.get("/api/v1/liquidaciones-api/despachos?month=7&year=2026")
    assert r.status_code == 200, r.text
    por_id = {f["id"]: f for f in r.json()["results"]}
    assert por_id[1]["proyecto"] == "El Molino"
    # El tópico crudo se conserva: es con lo que se diagnostica el proyecto.
    assert por_id[1]["topico"] == "elmolino"
    # La Reserva cruza por `topico_liquidaciones`, no por `sub_project`.
    assert por_id[2]["proyecto"] == "MGS 0012 La Reserva"


def test_despacho_sin_cruce_cae_al_topico(client, monkeypatch):
    """Es preferible ver el tópico crudo que una fila sin nombre."""
    monkeypatch.setattr(liquidaciones_api, "listar_liquidaciones_mercado",
                        lambda **kw: list(DESPACHOS))
    r = client.get("/api/v1/liquidaciones-api/despachos?month=7&year=2026")
    fila = next(f for f in r.json()["results"] if f["id"] == 3)
    assert fila["proyecto"] == "planta_que_no_esta_en_esta_base"


def test_despachos_vienen_del_mas_reciente(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_liquidaciones_mercado",
                        lambda **kw: list(DESPACHOS))
    r = client.get("/api/v1/liquidaciones-api/despachos?month=7&year=2026")
    fechas = [f["fecha"] for f in r.json()["results"]]
    assert fechas == sorted(fechas, reverse=True)


def test_despachos_conservan_fecha_precio_y_contrato(client, monkeypatch):
    """Los tres datos que se perdían al aplanar el estado de resultados."""
    monkeypatch.setattr(liquidaciones_api, "listar_liquidaciones_mercado",
                        lambda **kw: list(DESPACHOS))
    fila = next(f for f in client.get(
        "/api/v1/liquidaciones-api/despachos?month=7&year=2026").json()["results"]
        if f["id"] == 1)
    assert fila["fecha"] == "2026-07-01"
    assert fila["valor"] == 5000.0
    assert fila["codigo_contrato"] == "84962"


def test_despachos_pasan_el_filtro_de_tipo_a_la_api(client, monkeypatch):
    capturado = {}

    def fake(**kw):
        capturado.update(kw)
        return []

    monkeypatch.setattr(liquidaciones_api, "listar_liquidaciones_mercado", fake)
    client.get("/api/v1/liquidaciones-api/despachos?month=7&year=2026&data_type=purchase")
    assert capturado["data_type"] == "purchase"
    assert capturado["month"] == 7 and capturado["year"] == 2026


# ── Consumo ──────────────────────────────────────────────────────────────────

def _dia(project, fecha, valor_por_hora):
    fila = {"id": 1, "date": fecha, "version": "txf", "project": project}
    fila.update({f"con_hour{h:02d}": valor_por_hora for h in range(1, 25)})
    return fila


def test_consumo_arma_las_24_horas_y_su_total(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_contratos_despachados",
                        lambda **kw: [_dia("elmolino", "2026-07-05", 2.5)])
    r = client.get("/api/v1/liquidaciones-api/consumo?month=7&year=2026")
    assert r.status_code == 200, r.text
    fila = r.json()["results"][0]
    assert len(fila["horas"]) == 24
    assert fila["total_diario"] == 60.0
    assert fila["proyecto"] == "El Molino"


def test_consumo_no_confunde_hora_1_con_hora_24(client, monkeypatch):
    """Las horas van de la 01 a la 24; un off-by-one aquí desplaza toda la fila."""
    fila = _dia("elmolino", "2026-07-05", 0.0)
    fila["con_hour01"] = 11.0
    fila["con_hour24"] = 99.0
    monkeypatch.setattr(liquidaciones_api, "listar_contratos_despachados", lambda **kw: [fila])
    horas = client.get(
        "/api/v1/liquidaciones-api/consumo?month=7&year=2026").json()["results"][0]["horas"]
    assert horas[0] == 11.0 and horas[23] == 99.0


def test_consumo_con_horas_vacias_no_revienta(client, monkeypatch):
    """Un hueco en el archivo de XM no debe tumbar la pantalla entera."""
    fila = _dia("elmolino", "2026-07-05", 1.0)
    fila["con_hour07"] = None
    monkeypatch.setattr(liquidaciones_api, "listar_contratos_despachados", lambda **kw: [fila])
    res = client.get("/api/v1/liquidaciones-api/consumo?month=7&year=2026").json()["results"][0]
    assert res["horas"][6] is None
    assert res["total_diario"] == 23.0


def test_consumo_ordena_del_dia_mas_reciente(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_contratos_despachados", lambda **kw: [
        _dia("elmolino", "2026-07-01", 1),
        _dia("elmolino", "2026-07-31", 1),
        _dia("elmolino", "2026-07-15", 1),
    ])
    fechas = [f["fecha"] for f in client.get(
        "/api/v1/liquidaciones-api/consumo?month=7&year=2026").json()["results"]]
    assert fechas == ["2026-07-31", "2026-07-15", "2026-07-01"]


# ── IPP histórico ────────────────────────────────────────────────────────────

IPPS = [
    {"id": 42, "year": 2026, "month": 7, "ipp": 186.00, "date": "2026-07-10T15:46:07-05:00"},
    {"id": 45, "year": 2026, "month": 7, "ipp": 186.35, "date": "2026-07-19T08:27:29-05:00"},
    {"id": 41, "year": 2026, "month": 6, "ipp": 187.43, "date": "2026-06-22T10:59:49-05:00"},
]


def test_ipp_marca_una_sola_vigente_por_mes(client, monkeypatch):
    """Cada consulta al DANE deja su fila; solo la última del mes es la que vale."""
    monkeypatch.setattr(liquidaciones_api, "listar_ipp_historico", lambda **kw: list(IPPS))
    filas = client.get("/api/v1/liquidaciones-api/ipp").json()

    julio = [f for f in filas if f["mes"] == 7]
    assert [f["id"] for f in julio if f["vigente"]] == [45]
    # Junio tiene una sola consulta: esa es la vigente.
    assert next(f for f in filas if f["mes"] == 6)["vigente"] is True


def test_ipp_viene_del_periodo_mas_reciente(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_ipp_historico", lambda **kw: list(IPPS))
    filas = client.get("/api/v1/liquidaciones-api/ipp").json()
    assert (filas[0]["anio"], filas[0]["mes"]) == (2026, 7)
    assert filas[-1]["mes"] == 6


def test_ipp_sin_consultas_devuelve_vacio(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "listar_ipp_historico", lambda **kw: [])
    assert client.get("/api/v1/liquidaciones-api/ipp?year=2026&month=1").json() == []


# ── Ids de Quoia ─────────────────────────────────────────────────────────────

def test_actualizar_quoia_solo_manda_lo_enviado(client, monkeypatch):
    """`null` borra el id en esa API: un campo omitido no puede viajar como null."""
    enviado = {}

    def fake(topico, cambios):
        enviado.update({"topico": topico, **cambios})
        return {"topic": topico, "quoia_node_id": "1651"}

    monkeypatch.setattr(liquidaciones_api, "actualizar_subproyecto", fake)
    r = client.patch("/api/v1/liquidaciones-api/subproyectos/agustin_3",
                     json={"quoia_node_id": "1651"})
    assert r.status_code == 200, r.text
    assert enviado == {"topico": "agustin_3", "quoia_node_id": "1651"}


def test_actualizar_quoia_acepta_topicos_con_espacios(client, monkeypatch):
    """Varios subproyectos se llaman «MGS Mapale», con espacio."""
    vistos = []
    monkeypatch.setattr(liquidaciones_api, "actualizar_subproyecto",
                        lambda t, c: vistos.append(t) or {"topic": t})
    r = client.patch("/api/v1/liquidaciones-api/subproyectos/MGS%20Mapale",
                     json={"quoia_report_gen_id": "113"})
    assert r.status_code == 200, r.text
    assert vistos == ["MGS Mapale"]


def test_actualizar_quoia_sin_campos_es_400(client):
    assert client.patch("/api/v1/liquidaciones-api/subproyectos/x", json={}).status_code == 400
