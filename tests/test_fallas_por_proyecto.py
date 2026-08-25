"""GET /fallas/por-proyecto — las fallas de una planta para un consumidor externo.

Lo que se protege acá:

  · las tres cubetas públicas (vigente / programado / terminado) mapean bien
    los seis estados internos, y `programado` NO se cuela dentro de `vigente`
    aunque no sea un estado final;
  · un estado agregado al catálogo después cae solo en una cubeta según
    `es_estado_final` — nunca queda invisible para el consumidor;
  · el `resumen` cuenta las tres cubetas SIEMPRE, sin importar cuál se filtró:
    es lo que le dice al consumidor que hay más de lo que está viendo;
  · sólo salen fallas de ESA planta, y nunca las borradas (deleted_at);
  · las tres llaves de identificación (proyecto_id / api_id_unergy / nombre)
    resuelven la misma planta, y un nombre ambiguo da 409 en vez de elegir
    la planta equivocada en silencio;
  · la ficha pública no filtra correos de usuarios internos.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.models.fallas import (
    Falla, FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria,
    FallaCatResolucion, FallaSeguimiento, FallaIntervalo, FallaInversor,
)
from app.services.fallas.consulta_publica import grupo_de_estado, codigos_de_grupo


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 8, 25)

# Los seis estados reales del catálogo (app/seeds/seed_data.py).
ESTADOS = [
    ("programado",   "Programado",   0, False),
    ("abierta",      "Abierta",      1, False),
    ("en_gestion",   "En gestión",   2, False),
    ("en_espera",    "En espera",    3, False),
    ("cerrada",      "Cerrada",      4, True),
    ("sin_solucion", "Sin solución", 5, True),
]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, Usuario.__table__,
        FallaCatCategoria.__table__, FallaCatTipo.__table__, FallaCatEstado.__table__,
        FallaCatPrioridad.__table__, FallaCatResolucion.__table__,
        Falla.__table__, FallaSeguimiento.__table__, FallaIntervalo.__table__,
        FallaInversor.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def cliente(db):
    """App mínima con sólo el router de fallas, autenticación stubeada.

    El stub de get_current_user vale porque lo que se prueba acá es la consulta,
    no el guardia: en producción esa dependencia es la que valida el X-API-Key
    (ver app/api/v1/auth.py) y es la misma para todos los endpoints.
    """
    from app.core.database import get_db
    from app.api.v1 import fallas as fallas_mod

    app = FastAPI()
    app.include_router(fallas_mod.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[fallas_mod.get_current_user] = lambda: types.SimpleNamespace(
        id=1, nombre="Servicio externo")
    return TestClient(app)


@pytest.fixture
def datos(db):
    """Una planta con una falla por estado + una planta vecina + una borrada."""
    estados = {}
    for i, (codigo, etiqueta, orden, final) in enumerate(ESTADOS, start=1):
        e = FallaCatEstado(id=i, codigo=codigo, etiqueta=etiqueta,
                           orden=orden, es_estado_final=final)
        db.add(e)
        estados[codigo] = e
    db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=3))
    db.add(Usuario(id=1, nombre="Laura", email="laura@unergy.io",
                   password_hash="x", rol="operaciones", activo=True))

    planta = Proyecto(id=10, nombre_comercial="Santa Fe 2", sub_project="SF2",
                      estado="en_operacion", municipio="Sincelejo", departamento="Sucre",
                      potencia_instalada_kwp=990)
    vecina = Proyecto(id=11, nombre_comercial="Marimonda", sub_project="MAR",
                      estado="en_operacion")
    db.add_all([planta, vecina])
    db.flush()

    n = 0
    for codigo in estados:
        n += 1
        db.add(Falla(
            id=n, codigo_interno=f"FAL-2026-{n:05d}", proyecto_id=planta.id,
            estado_id=estados[codigo].id, prioridad_id=1, registrado_por_id=1,
            descripcion=f"falla en estado {codigo}",
            fecha_identificacion=HOY - dt.timedelta(days=n),
            fecha_programada=HOY + dt.timedelta(days=3) if codigo == "programado" else None,
        ))
    # Ruido que NO debe salir: una falla de la planta vecina y una borrada.
    db.add(Falla(id=90, codigo_interno="FAL-2026-00090", proyecto_id=vecina.id,
                 estado_id=estados["abierta"].id, prioridad_id=1, registrado_por_id=1,
                 descripcion="de la vecina", fecha_identificacion=HOY))
    db.add(Falla(id=91, codigo_interno="FAL-2026-00091", proyecto_id=planta.id,
                 estado_id=estados["abierta"].id, prioridad_id=1, registrado_por_id=1,
                 descripcion="borrada", fecha_identificacion=HOY,
                 deleted_at=dt.datetime(2026, 8, 1)))
    db.commit()
    return {"planta": planta, "vecina": vecina, "estados": estados}


# ── El mapeo de estados ──────────────────────────────────────────────────────

def test_los_seis_estados_caen_en_la_cubeta_correcta():
    esperado = {
        "abierta": "vigente", "en_gestion": "vigente", "en_espera": "vigente",
        "programado": "programado",
        "cerrada": "terminado", "sin_solucion": "terminado",
    }
    for codigo, etiqueta, orden, final in ESTADOS:
        assert grupo_de_estado(codigo, final) == esperado[codigo], codigo


def test_programado_no_se_cuela_en_vigente_aunque_no_sea_final():
    # `programado` es es_estado_final=False; si el mapeo se hiciera sólo con esa
    # bandera caería en "vigente" y el consumidor no podría separarlos.
    assert grupo_de_estado("programado", False) == "programado"
    catalogo = [types.SimpleNamespace(codigo=c, es_estado_final=f)
                for c, _, _, f in ESTADOS]
    assert "programado" not in codigos_de_grupo(catalogo, "vigente")
    assert codigos_de_grupo(catalogo, "programado") == ["programado"]


def test_estado_nuevo_del_catalogo_no_queda_invisible():
    # Si mañana alguien agrega un estado, tiene que caer en alguna cubeta.
    catalogo = [types.SimpleNamespace(codigo=c, es_estado_final=f) for c, _, _, f in ESTADOS]
    catalogo.append(types.SimpleNamespace(codigo="escalada_om", es_estado_final=False))
    catalogo.append(types.SimpleNamespace(codigo="anulada", es_estado_final=True))
    cubiertos = set()
    for grupo in ("vigente", "programado", "terminado"):
        cubiertos |= set(codigos_de_grupo(catalogo, grupo))
    assert cubiertos == {e.codigo for e in catalogo}
    assert "escalada_om" in codigos_de_grupo(catalogo, "vigente")
    assert "anulada" in codigos_de_grupo(catalogo, "terminado")


# ── El endpoint ──────────────────────────────────────────────────────────────

def test_vigente_es_el_default_y_trae_las_tres_no_finales_menos_programado(cliente, datos):
    r = cliente.get("/api/v1/fallas/por-proyecto", params={"proyecto_id": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estado_consultado"] == "vigente"
    assert sorted(body["estados_incluidos"]) == ["abierta", "en_espera", "en_gestion"]
    assert body["total"] == 3
    assert {f["estado"]["codigo"] for f in body["items"]} == {"abierta", "en_gestion", "en_espera"}
    assert all(f["estado"]["grupo"] == "vigente" for f in body["items"])


def test_programado_trae_solo_esa_y_con_su_fecha(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto",
                       params={"proyecto_id": 10, "estado": "programado"}).json()
    assert body["total"] == 1
    (falla,) = body["items"]
    assert falla["estado"]["codigo"] == "programado"
    assert falla["fecha_programada"] == "2026-08-28"


def test_terminado_trae_los_dos_estados_finales(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto",
                       params={"proyecto_id": 10, "estado": "terminado"}).json()
    assert body["total"] == 2
    assert {f["estado"]["codigo"] for f in body["items"]} == {"cerrada", "sin_solucion"}
    assert all(f["estado"]["es_estado_final"] for f in body["items"])


def test_todas_trae_las_seis(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto",
                       params={"proyecto_id": 10, "estado": "todas"}).json()
    assert body["total"] == 6


def test_el_resumen_cuenta_las_tres_cubetas_aunque_se_filtre_una(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto",
                       params={"proyecto_id": 10, "estado": "programado"}).json()
    assert body["total"] == 1                      # lo que trae la página
    assert body["resumen"] == {                    # lo que hay en total
        "vigente": 3, "programado": 1, "terminado": 2, "total": 6,
    }


def test_no_trae_fallas_de_otra_planta_ni_borradas(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto",
                       params={"proyecto_id": 10, "estado": "todas"}).json()
    codigos = {f["codigo"] for f in body["items"]}
    assert "FAL-2026-00090" not in codigos, "se coló una falla de la planta vecina"
    assert "FAL-2026-00091" not in codigos, "se coló una falla borrada"
    assert body["resumen"]["total"] == 6, "la borrada no debe contar en el resumen"


def test_las_tres_llaves_resuelven_la_misma_planta(cliente, datos):
    por_id = cliente.get("/api/v1/fallas/por-proyecto", params={"proyecto_id": 10}).json()
    por_api = cliente.get("/api/v1/fallas/por-proyecto", params={"api_id_unergy": "SF2"}).json()
    # sin tildes/mayúsculas: el match normaliza
    por_nombre = cliente.get("/api/v1/fallas/por-proyecto", params={"nombre": "  SANTA fe 2 "}).json()
    assert por_id["proyecto"]["id"] == por_api["proyecto"]["id"] == por_nombre["proyecto"]["id"] == 10
    assert por_id["total"] == por_api["total"] == por_nombre["total"] == 3
    assert por_id["proyecto"]["api_id_unergy"] == "SF2"


def test_nombre_ambiguo_da_409_en_vez_de_elegir_una(cliente, datos, db):
    # Ojo: la 12 solo se diferencia por la TILDE. Un prefiltro ILIKE sobre el
    # texto crudo no la ve y el nombre se resolvería como único -> la integración
    # se llevaría las fallas de la planta equivocada sin enterarse.
    db.add(Proyecto(id=12, nombre_comercial="Santa Fé 2", estado="en_operacion"))
    db.commit()
    r = cliente.get("/api/v1/fallas/por-proyecto", params={"nombre": "Santa Fe 2"})
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["nombre_ambiguo"] is True
    assert {c["id"] for c in detalle["candidatos"]} == {10, 12}


def test_hay_que_mandar_exactamente_una_llave(cliente, datos):
    assert cliente.get("/api/v1/fallas/por-proyecto").status_code == 422
    r = cliente.get("/api/v1/fallas/por-proyecto",
                    params={"proyecto_id": 10, "api_id_unergy": "SF2"})
    assert r.status_code == 422


def test_planta_inexistente_da_404(cliente, datos):
    assert cliente.get("/api/v1/fallas/por-proyecto", params={"proyecto_id": 999}).status_code == 404
    assert cliente.get("/api/v1/fallas/por-proyecto", params={"api_id_unergy": "NOPE"}).status_code == 404


def test_estado_invalido_dice_cuales_valen(cliente, datos):
    r = cliente.get("/api/v1/fallas/por-proyecto",
                    params={"proyecto_id": 10, "estado": "abierta"})
    assert r.status_code == 422
    detalle = r.json()["detail"]
    for grupo in ("vigente", "programado", "terminado", "todas"):
        assert grupo in detalle


def test_filtra_por_rango_de_fechas(cliente, datos):
    body = cliente.get("/api/v1/fallas/por-proyecto", params={
        "proyecto_id": 10, "estado": "todas",
        "desde": "2026-08-22", "hasta": "2026-08-24",
    }).json()
    assert body["total"] == 3
    assert body["resumen"]["total"] == 3, "el resumen respeta el mismo rango de fechas"
    for f in body["items"]:
        assert "2026-08-22" <= f["fecha_identificacion"] <= "2026-08-24"


def test_rango_invertido_da_422(cliente, datos):
    r = cliente.get("/api/v1/fallas/por-proyecto", params={
        "proyecto_id": 10, "desde": "2026-08-25", "hasta": "2026-08-01"})
    assert r.status_code == 422


def test_pagina(cliente, datos):
    p1 = cliente.get("/api/v1/fallas/por-proyecto",
                     params={"proyecto_id": 10, "estado": "todas", "size": 4, "page": 1}).json()
    p2 = cliente.get("/api/v1/fallas/por-proyecto",
                     params={"proyecto_id": 10, "estado": "todas", "size": 4, "page": 2}).json()
    assert p1["total"] == p2["total"] == 6
    assert p1["pages"] == 2
    assert len(p1["items"]) == 4 and len(p2["items"]) == 2
    assert not ({f["id"] for f in p1["items"]} & {f["id"] for f in p2["items"]})


def test_la_ficha_no_filtra_correos_internos(cliente, datos):
    crudo = cliente.get("/api/v1/fallas/por-proyecto",
                        params={"proyecto_id": 10, "estado": "todas"}).text
    assert "@unergy.io" not in crudo


def test_la_ruta_no_la_captura_el_detalle_por_id(cliente, datos):
    # /fallas/{id} está declarada después y tiene id:int — si estuviera antes,
    # "por-proyecto" chocaría contra ella y saldría un 422 de path param.
    r = cliente.get("/api/v1/fallas/por-proyecto", params={"proyecto_id": 10})
    assert r.status_code == 200
    assert "proyecto" in r.json()
