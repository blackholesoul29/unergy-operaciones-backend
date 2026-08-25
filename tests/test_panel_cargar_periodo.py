"""Armar los paneles de un período desde la API, sin subir archivos.

NEU y Nitro se saltan a propósito: su dato de API está malo y siguen cargando el
Excel. Saltarlos en silencio sería peor que no hacer nada -- parecería que el
período quedó completo-- así que el endpoint informa cuáles omitió.
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import panel_contable
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.base import Base
from app.models.panel_contable import (
    ClasificacionLiquidacion, PanelContable, PanelContableLinea,
)
from app.models.proyectos import Proyecto
from app.services import liquidaciones_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    """SQLite solo autoincrementa las claves declaradas INTEGER, y los modelos
    usan BigInteger. Sin esto, insertar un panel falla por la PK en NULL."""
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Proyecto(id=1, nombre_comercial="MGS 0007 La Paz Vallenata",
                   sub_project="vallenata"))
    s.add(Proyecto(id=2, nombre_comercial="Minigranja Solar Baraya",
                   sub_project="baraya"))
    # La Reserva se llama distinto en cada API: cruza por topico_liquidaciones.
    s.add(Proyecto(id=3, nombre_comercial="MGS 0012 La Reserva",
                   sub_project="reserva", topico_liquidaciones="MGS 0012 La Reserva"))
    s.add(ClasificacionLiquidacion(proyecto_id=2, periodo="2026-07", tipo="neu"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(panel_contable.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=1, rol=types.SimpleNamespace(value="admin"))
    return TestClient(app)


def _proy(topico, nombre, ingreso):
    return {
        "project": topico, "project_name": nombre,
        "generacion_kwh": 213_000.0, "importacion_kwh": 715.71,
        "ingreso_bruto": ingreso, "venta": ingreso, "compra": 0.0,
        "tiene_bolsa": False, "comercializadores": ["Terpel"],
        "ingresos_detalle": [{"concepto": "Terpel Venta", "data_type": "dispatch",
                              "energia_kwh": 213_000.0, "valor": ingreso}],
        "comercializacion": [], "participantes": [], "warnings": [],
    }


RESPUESTA_API = {
    "month": 7, "year": 2026, "version": "txf", "count": 4,
    "results": [
        _proy("vallenata", "MGS 0007 La Paz Vallenata", 77_464_585.0),
        _proy("baraya", "Minigranja Solar Baraya", 56_978_276.0),
        _proy("MGS 0012 La Reserva", "MGS 0012 La Reserva", 60_435_889.0),
        _proy("planta_que_no_esta_en_esta_base", "Otra", 1_000.0),
    ],
    "errors": [],
}


@pytest.fixture(autouse=True)
def _api(monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "estado_resultados_json",
                        lambda **kw: RESPUESTA_API)


def _cargar(client, **extra):
    cuerpo = {"periodo": "2026-07", "tipo": "oficial"}
    cuerpo.update(extra)
    r = client.post("/api/v1/panel-contable/cargar-periodo", json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


def test_arma_el_panel_de_un_proyecto_normal(client, db):
    _cargar(client)
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 1).one()
    assert float(panel.ingreso_bruto_cop) == 77_464_585.0


def test_le_pone_lineas_al_panel(client, db):
    _cargar(client)
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 1).one()
    assert db.query(PanelContableLinea).filter(
        PanelContableLinea.panel_id == panel.id).count() > 0


def test_cruza_por_topico_de_liquidaciones(client, db):
    """La Reserva se llama `reserva` en generación y distinto en liquidaciones."""
    _cargar(client)
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 3).one()
    assert float(panel.ingreso_bruto_cop) == 60_435_889.0


def test_no_toca_los_neu(client, db):
    """Baraya es NEU: su panel sigue siendo el que se cargó del Excel."""
    _cargar(client)
    assert db.query(PanelContable).filter(PanelContable.proyecto_id == 2).count() == 0


def test_informa_que_omitio_los_neu(client):
    """Saltarlos en silencio haría creer que el período quedó completo."""
    d = _cargar(client)
    assert any(o["proyecto"] == "Minigranja Solar Baraya" and o["motivo"] == "neu"
               for o in d["omitidos"])


def test_informa_los_que_no_cruzan_con_esta_base(client):
    d = _cargar(client)
    assert "planta_que_no_esta_en_esta_base" in d["sin_cruce"]


def test_cuenta_los_que_armo(client):
    d = _cargar(client)
    assert d["armados"] == 2


def test_recargar_no_duplica_paneles(client, db):
    """Volver a cargar el período reemplaza, no acumula."""
    _cargar(client)
    _cargar(client)
    assert db.query(PanelContable).filter(PanelContable.proyecto_id == 1).count() == 1


def test_recargar_no_duplica_lineas(client, db):
    _cargar(client)
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 1).one()
    antes = db.query(PanelContableLinea).filter(
        PanelContableLinea.panel_id == panel.id).count()
    _cargar(client)
    assert db.query(PanelContableLinea).filter(
        PanelContableLinea.panel_id == panel.id).count() == antes


def test_la_preliquidacion_y_la_oficial_conviven(client, db):
    _cargar(client, tipo="oficial")
    _cargar(client, tipo="preliquidacion")
    assert db.query(PanelContable).filter(PanelContable.proyecto_id == 1).count() == 2


def test_rechaza_un_periodo_mal_formado(client):
    r = client.post("/api/v1/panel-contable/cargar-periodo",
                    json={"periodo": "julio", "tipo": "oficial"})
    assert r.status_code == 422


def test_normaliza_el_periodo(client, db):
    """`2026-7` y `2026-07` son el mismo mes."""
    _cargar(client, periodo="2026-7")
    assert db.query(PanelContable).filter(
        PanelContable.proyecto_id == 1).one().periodo == "2026-07"


def test_si_la_api_falla_devuelve_502(client, monkeypatch):
    def _explota(**kw):
        raise liquidaciones_api.LiquidacionesAPIError("sin conexión")

    monkeypatch.setattr(liquidaciones_api, "estado_resultados_json", _explota)
    r = client.post("/api/v1/panel-contable/cargar-periodo",
                    json={"periodo": "2026-07", "tipo": "oficial"})
    assert r.status_code == 502


def test_devuelve_los_errores_que_reporta_la_api(client, monkeypatch):
    monkeypatch.setattr(liquidaciones_api, "estado_resultados_json",
                        lambda **kw: {**RESPUESTA_API, "errors": ["x no se pudo calcular"]})
    assert _cargar(client)["errores_api"] == ["x no se pudo calcular"]


def test_marca_el_panel_como_armado_desde_la_api(client, db):
    """Sin esta marca no hay forma de saber con qué se construyó un panel: los
    ingresos no tienen columna `fuente`, solo los costos."""
    _cargar(client)
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 1).one()
    assert panel.origen == "api"


def test_los_paneles_del_excel_siguen_diciendo_er(db):
    """El default protege lo ya cargado: todo lo anterior a la migración es 'er'."""
    p = PanelContable(proyecto_id=1, periodo="2026-06", tipo="oficial")
    db.add(p)
    db.commit()
    assert p.origen == "er"


# ── El Excel quedó solo para NEU y Nitro ─────────────────────────────────────

def test_cargar_er_rechaza_un_proyecto_normal(client, db, monkeypatch, tmp_path):
    """Desde la migración, un proyecto normal ya no se carga por Excel: se arma
    desde la API. Dejar los dos caminos abiertos permitiría pisar sin querer un
    panel armado desde la API con un Excel viejo."""
    archivo = tmp_path / "Estado resultados Vallenata 7 2026.xlsx"
    archivo.write_bytes(b"no importa: se rechaza antes de parsearlo")

    monkeypatch.setattr(
        panel_contable, "extraer_proyecto_de_archivo",
        lambda *a, **k: {"id": 1, "nombre_comercial": "MGS 0007 La Paz Vallenata"})

    with archivo.open("rb") as fh:
        r = client.post("/api/v1/panel-contable/cargar-er",
                        data={"periodo": "2026-07", "tipo": "oficial",
                              "tipo_carga": "normal"},
                        files={"files": ("er.xlsx", fh,
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    rechazos = r.json().get("rechazados") or []
    assert rechazos, "un proyecto normal debería quedar rechazado"
    assert "API" in rechazos[0]["mensaje"]
