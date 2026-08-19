"""API de consulta de proyectos para un usuario con cuenta (ver
docs/API_PROYECTOS.md). Dos endpoints de solo lectura:

  GET /proyectos/lista            -> todos los proyectos, campos livianos
  GET /proyectos/buscar?nombre=X  -> detalle resuelto por nombre

El match por nombre es EXACTO pero normalizado (tolera mayusculas, tildes,
guiones y espacios de mas). Deliberadamente NO es fuzzy: un nombre parcial da
404 en vez de adivinar, y un nombre que coincide con varios proyectos da 409
con los candidatos, porque nombre_comercial no tiene UNIQUE y en produccion
existen duplicados reales.
"""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.proyectos import (
    ProyectoInversionista, ProyectoInfoTecnica, ProyectoGrupoPanel,
    ProyectoInversor,
)
from app.models.contactos import ProyectoAreaContacto, Contacto
from app.models.servicios import ServicioRepresentacion
from app.models.clientes import Cliente
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.contratos import PPAContrato
from app.api.v1 import proyectos as proyectos_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    # StaticPool + check_same_thread=False: los tests de enrutamiento usan
    # TestClient, que ejecuta el endpoint sincrono en un hilo aparte. Con el pool
    # por defecto ese hilo recibiria una conexion nueva -- y en SQLite ":memory:"
    # una conexion nueva es una base VACIA ("no such table: proyectos").
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, Cliente.__table__, ProyectoInversionista.__table__,
            ProyectoInfoTecnica.__table__, ProyectoGrupoPanel.__table__,
            ProyectoInversor.__table__, ProyectoAreaContacto.__table__, Contacto.__table__,
            ServicioRepresentacion.__table__,
            # _get_proyecto_or_404 hace selectinload(Proyecto.fronteras)
            # .selectinload(Frontera.operador) -- sin estas dos tablas el eager
            # load falla con "no such table: fronteras".
            Frontera.__table__, OperadorRed.__table__,
            # ProyectoOut expone `ppa_contratos` (d01e8a9), que se resuelve por
            # la tabla puente: sin ella el eager load falla con
            # "no such table: ppa_contrato_proyectos".
            PPAContrato.__table__, Base.metadata.tables["ppa_contrato_proyectos"],
        Base.metadata.tables["oportunidad_oferta_proyectos"],
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _proyecto(db, **kw):
    p = Proyecto(id=next(_ids), **kw)
    db.add(p)
    db.commit()
    return p


# ── GET /proyectos/lista ──────────────────────────────────────────────────────

def test_lista_devuelve_todos_los_proyectos_ordenados_por_nombre(db):
    _proyecto(db, nombre_comercial="Zulia")
    _proyecto(db, nombre_comercial="Aguachica")
    _proyecto(db, nombre_comercial="Marimonda")

    out = proyectos_api.listar_proyectos_simple(db=db, _=None)

    assert out["total"] == 3
    assert [i["nombre_comercial"] for i in out["items"]] == ["Aguachica", "Marimonda", "Zulia"]


def test_lista_solo_trae_los_campos_livianos(db):
    _proyecto(
        db,
        nombre_comercial="Minigranja 0029 - Monterrubio",
        estado="en_operacion",
        tipo_proyecto="minigranja",
        municipio="Monterrubio",
        departamento="Sucre",
        potencia_instalada_kwp=990.0,
        sub_project="monterrubio",
        codigo_tsf="MGS-0029",
    )

    out = proyectos_api.listar_proyectos_simple(db=db, _=None)
    item = out["items"][0]

    assert set(item) == {
        "id", "nombre_comercial", "estado", "tipo_proyecto",
        "municipio", "departamento", "potencia_instalada_kwp",
        "sub_project", "codigo_tsf",
    }
    assert item["estado"] == "en_operacion"
    assert item["tipo_proyecto"] == "minigranja"
    assert item["potencia_instalada_kwp"] == 990.0
    assert item["codigo_tsf"] == "MGS-0029"


def test_lista_excluye_proyectos_borrados(db):
    _proyecto(db, nombre_comercial="Vigente")
    _proyecto(db, nombre_comercial="Borrado", deleted_at=datetime.now(timezone.utc))

    out = proyectos_api.listar_proyectos_simple(db=db, _=None)

    assert out["total"] == 1
    assert out["items"][0]["nombre_comercial"] == "Vigente"


# ── GET /proyectos/buscar ─────────────────────────────────────────────────────

def test_buscar_por_nombre_exacto_devuelve_el_detalle(db):
    p = _proyecto(db, nombre_comercial="Marimonda", municipio="Sahagún")
    _proyecto(db, nombre_comercial="Otro Proyecto")

    out = proyectos_api.buscar_proyecto_por_nombre(nombre="Marimonda", db=db, _=None)

    assert out.id == p.id
    assert out.municipio == "Sahagún"


def test_buscar_tolera_mayusculas_tildes_guiones_y_espacios(db):
    p = _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")

    for entrada in (
        "minigranja 0029 monterrubio",
        "MINIGRANJA 0029 - MONTERRUBIO",
        "Minigranja  0029  –  Monterrúbio",
        "  Minigranja 0029 - Monterrubio  ",
    ):
        out = proyectos_api.buscar_proyecto_por_nombre(nombre=entrada, db=db, _=None)
        assert out.id == p.id, f"no resolvio con la entrada {entrada!r}"


def test_buscar_con_nombre_parcial_da_404(db):
    # "monterrubio" a secas NO coincide: el match es exacto normalizado, no fuzzy.
    _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.buscar_proyecto_por_nombre(nombre="monterrubio", db=db, _=None)

    assert exc.value.status_code == 404
    # El mensaje repite el texto tal como lo mando quien llama, no el normalizado.
    assert "monterrubio" in exc.value.detail
    assert "/proyectos/lista" in exc.value.detail


@pytest.mark.parametrize("entrada", [
    "monterrubio",                    # parcial
    "Minigranja 0029 - Monterubio",   # mal escrito
    "0029 Monterrubio Minigranja",    # palabras desordenadas
])
def test_buscar_no_adivina(db, entrada):
    """Los tres casos que docs/API_PROYECTOS.md promete que dan 404. El match
    compara la cadena normalizada completa, asi que ni un typo ni un reordenamiento
    de palabras coinciden."""
    _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.buscar_proyecto_por_nombre(nombre=entrada, db=db, _=None)

    assert exc.value.status_code == 404


def test_buscar_con_nombre_ambiguo_da_409_con_candidatos(db):
    # nombre_comercial no tiene UNIQUE; en produccion hay duplicados reales.
    p1 = _proyecto(db, nombre_comercial="Chinú Sur")
    p2 = _proyecto(db, nombre_comercial="Chinu Sur")

    with pytest.raises(HTTPException) as exc:
        proyectos_api.buscar_proyecto_por_nombre(nombre="Chinu Sur", db=db, _=None)

    assert exc.value.status_code == 409
    assert exc.value.detail["nombre_ambiguo"] is True
    assert {c["id"] for c in exc.value.detail["candidatos"]} == {p1.id, p2.id}


def test_buscar_cae_a_nombre_bitacora_cuando_no_hay_match_comercial(db):
    p = _proyecto(db, nombre_comercial="Minigranja 0031 - El Carmen",
                  nombre_bitacora="Carmen de Bolívar")

    out = proyectos_api.buscar_proyecto_por_nombre(nombre="carmen de bolivar", db=db, _=None)

    assert out.id == p.id


def test_buscar_cae_a_nombre_clientes_cuando_no_hay_match_comercial(db):
    p = _proyecto(db, nombre_comercial="Minigranja 0044 - Sincelejo",
                  nombre_clientes="Planta Sincelejo Norte")

    out = proyectos_api.buscar_proyecto_por_nombre(
        nombre="planta sincelejo norte", db=db, _=None)

    assert out.id == p.id


def test_buscar_prefiere_nombre_comercial_sobre_bitacora(db):
    # Etapa 1 (nombre_comercial) gana: la etapa 2 no corre ni suma candidatos,
    # asi que esto NO es ambiguo.
    ganador = _proyecto(db, nombre_comercial="Marimonda")
    _proyecto(db, nombre_comercial="Otro", nombre_bitacora="Marimonda")

    out = proyectos_api.buscar_proyecto_por_nombre(nombre="Marimonda", db=db, _=None)

    assert out.id == ganador.id


def test_buscar_ignora_proyectos_borrados(db):
    _proyecto(db, nombre_comercial="Marimonda", deleted_at=datetime.now(timezone.utc))

    with pytest.raises(HTTPException) as exc:
        proyectos_api.buscar_proyecto_por_nombre(nombre="Marimonda", db=db, _=None)

    assert exc.value.status_code == 404


# ── Enrutamiento HTTP real ────────────────────────────────────────────────────
# Los tests de arriba llaman las funciones directo, asi que NO cubren dos cosas
# que solo existen a nivel de FastAPI:
#   1. El orden de declaracion. /{id} esta tipado int: si /lista y /buscar
#      quedaran declaradas despues, FastAPI intentaria convertir "lista" a
#      entero y devolveria 422 en vez de resolver la ruta.
#   2. La validacion del response_model (ProyectoListaResponse / ProyectoOut)
#      contra el payload que de verdad construyen los endpoints.
# Se monta un app minimo con solo este router, sin arrancar app.main.

@pytest.fixture
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(proyectos_api.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_ruta_lista_no_la_captura_el_path_param_de_id(db, client):
    _proyecto(db, nombre_comercial="Marimonda", estado="en_operacion",
              potencia_instalada_kwp=990.0)

    r = client.get("/api/v1/proyectos/lista")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["total"] == 1
    assert set(cuerpo["items"][0]) == {
        "id", "nombre_comercial", "estado", "tipo_proyecto",
        "municipio", "departamento", "potencia_instalada_kwp",
        "sub_project", "codigo_tsf",
    }
    assert cuerpo["items"][0]["potencia_instalada_kwp"] == 990.0


def test_ruta_buscar_no_la_captura_el_path_param_de_id(db, client):
    p = _proyecto(db, nombre_comercial="Minigranja 0029 - Monterrubio")

    r = client.get("/api/v1/proyectos/buscar", params={"nombre": "minigranja 0029 MONTERRÚBIO"})

    assert r.status_code == 200, r.text
    assert r.json()["id"] == p.id


def test_ruta_buscar_sin_nombre_da_422(db, client):
    r = client.get("/api/v1/proyectos/buscar")

    assert r.status_code == 422
