"""Endpoints de la seccion "Registros" via HTTP (TestClient + sqlite en memoria).

Los tests de servicio ya cubren la logica. Estos cubren lo que solo se rompe en
la capa HTTP: orden de las rutas, serializacion de los schemas y los codigos de
error. En particular, `/catalogos` va antes que `/{proyecto_id}`; si alguien
reordena los decoradores, "catalogos" se intenta parsear como id y estalla.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import registros_proyecto as api
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.base import Base
from app.models.proyectos import Proyecto
from app.models.registros_proyecto import (
    ArchivoDocumentoProyecto, DocumentoProyecto, ParametroProyecto,
)


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


class _Rol:
    value = "operaciones"


class _Usuario:
    rol = _Rol()
    nombre = "QA"


@pytest.fixture
def cliente():
    # StaticPool + check_same_thread: TestClient atiende las peticiones en otro
    # hilo, y sqlite en memoria le daria a cada conexion una base vacia distinta.
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, DocumentoProyecto.__table__,
        ArchivoDocumentoProyecto.__table__, ParametroProyecto.__table__,
    ])
    Sesion = sessionmaker(bind=engine)
    sesion = Sesion()
    sesion.add(Proyecto(nombre_comercial="MGS 0092 - San Luis de Since"))
    sesion.commit()

    aplicacion = FastAPI()
    aplicacion.include_router(api.router, prefix="/api/v1")
    aplicacion.dependency_overrides[get_db] = lambda: sesion
    aplicacion.dependency_overrides[get_current_user] = lambda: _Usuario()

    yield TestClient(aplicacion)
    sesion.close()


BASE = "/api/v1/registros-proyecto"


def test_catalogos_no_se_confunde_con_un_id_de_proyecto(cliente):
    r = cliente.get(f"{BASE}/catalogos")
    assert r.status_code == 200
    datos = r.json()
    assert [p["codigo"] for p in datos["procesos"]] == ["SIC", "CND"]
    assert len(datos["items"]) == 38
    assert len(datos["parametros"]) > 180


def test_indice_de_proyectos(cliente):
    r = cliente.get(BASE)
    assert r.status_code == 200
    assert r.json()[0]["sic"] == {"cargados": 0, "total": 28, "pct": 0}


def test_resumen_de_un_proyecto(cliente):
    r = cliente.get(f"{BASE}/1")
    assert r.status_code == 200
    datos = r.json()
    assert datos["nombre_comercial"] == "MGS 0092 - San Luis de Since"
    assert len(datos["procesos"]) == 2


def test_resumen_de_un_proyecto_inexistente_da_404(cliente):
    assert cliente.get(f"{BASE}/999").status_code == 404


def test_formulario_de_un_item(cliente):
    r = cliente.get(f"{BASE}/1/SIC/13")
    assert r.status_code == 200
    datos = r.json()
    assert datos["item"]["codigo"] == "13"
    assert datos["documento"]["estado"] == "PENDIENTE"
    claves = {c["clave"] for c in datos["campos"]}
    assert "medidor.numero_de_serie" in claves


def test_formulario_de_un_item_inexistente_da_404(cliente):
    assert cliente.get(f"{BASE}/1/SIC/99").status_code == 404


def test_el_proceso_se_acepta_en_minuscula(cliente):
    assert cliente.get(f"{BASE}/1/sic/01").status_code == 200


def test_montar_enlace_y_luego_quitarlo(cliente):
    r = cliente.post(f"{BASE}/1/SIC/11/archivos",
                     json={"url": "https://drive.google.com/x", "nombre_archivo": "unifilar.pdf"})
    assert r.status_code == 201
    archivo_id = r.json()["id"]

    assert cliente.get(f"{BASE}/1/SIC/11").json()["documento"]["estado"] == "CARGADO"
    assert cliente.delete(f"{BASE}/archivos/{archivo_id}").status_code == 204
    assert cliente.get(f"{BASE}/1/SIC/11").json()["documento"]["estado"] == "PENDIENTE"


def test_guardar_parametros_y_verlos_en_el_formulario(cliente):
    r = cliente.put(f"{BASE}/1/parametros", json={"valores": [
        {"clave": "medidor.numero_de_serie", "valor": "88866569",
         "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1},
    ]})
    assert r.status_code == 200
    assert r.json()[0]["valor"] == "88866569"

    campos = cliente.get(f"{BASE}/1/SIC/01").json()["campos"]
    serie = next(c for c in campos if c["clave"] == "medidor.numero_de_serie"
                 and c["equipo_tipo"] == "MEDIDOR_PRINCIPAL")
    assert serie["valor"] == "88866569"


def test_un_parametro_invalido_da_422_y_no_guarda_nada(cliente):
    r = cliente.put(f"{BASE}/1/parametros", json={"valores": [
        {"clave": "medidor.inventado", "valor": "x"},
    ]})
    assert r.status_code == 422
    assert cliente.get(f"{BASE}/1/parametros").json() == []


def test_actualizar_el_documento_con_su_radicado(cliente):
    r = cliente.patch(f"{BASE}/1/CND/9.1",
                      json={"radicado": "2025030000113791", "fecha_emision": "2025-12-18"})
    assert r.status_code == 200
    assert r.json()["radicado"] == "2025030000113791"
    assert r.json()["fecha_emision"] == "2025-12-18"


def test_un_estado_invalido_da_422(cliente):
    r = cliente.patch(f"{BASE}/1/SIC/01", json={"estado": "APROBADO"})
    assert r.status_code == 422


def test_un_rol_sin_permiso_no_puede_escribir(cliente):
    class _Monitoreo:
        class rol:
            value = "monitoreo"
        nombre = "QA"

    cliente.app.dependency_overrides[get_current_user] = lambda: _Monitoreo()
    assert cliente.get(f"{BASE}/1").status_code == 200          # leer si
    assert cliente.put(f"{BASE}/1/parametros",
                       json={"valores": []}).status_code == 403  # escribir no
