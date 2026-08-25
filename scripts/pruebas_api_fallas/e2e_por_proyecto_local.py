"""E2E: /fallas/por-proyecto contra la app REAL, autenticando con X-API-Key.

No va en tests/ porque tests/conftest.py stubea app.api.v1.auth (para no exigir
bcrypt/jose), y justamente lo que se quiere ejercitar acá es ese módulo real:
la resolución de la API Key contra la tabla api_keys. Se corre a mano.
"""
import datetime as dt
import hashlib
import os

os.environ["SECRET_KEY"] = "clave-de-pruebas-larga-0123456789abcdef"
os.environ["DATABASE_URL"] = "postgresql://u:p@127.0.0.1:5432/nodb"  # nunca se conecta

from sqlalchemy import create_engine, text, BigInteger
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from fastapi import FastAPI
from fastapi.testclient import TestClient


@compiles(JSONB, "sqlite")
def _jsonb(el, comp, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint(el, comp, **kw):
    return "INTEGER"


from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto
from app.models.usuarios import Usuario
from app.models.fallas import (
    Falla, FallaCatEstado, FallaCatPrioridad, FallaCatTipo, FallaCatCategoria,
    FallaCatResolucion, FallaSeguimiento, FallaIntervalo, FallaInversor,
)
from app.core.database import get_db
from app.api.v1.router import api_router

CLAVE = "uop_" + "a1b2c3d4" * 8          # el formato real: uop_ + 64 hex
HASH = hashlib.sha256(CLAVE.encode()).hexdigest()
HOY = dt.date(2026, 8, 25)

engine = create_engine("sqlite:///:memory:",
                       connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine, tables=[
    Proyecto.__table__, Usuario.__table__,
    FallaCatCategoria.__table__, FallaCatTipo.__table__, FallaCatEstado.__table__,
    FallaCatPrioridad.__table__, FallaCatResolucion.__table__,
    Falla.__table__, FallaSeguimiento.__table__, FallaIntervalo.__table__,
    FallaInversor.__table__,
])
db = sessionmaker(bind=engine)()

# api_keys no tiene modelo ORM (el router la maneja con SQL crudo).
db.execute(text("""
    CREATE TABLE api_keys (
        id INTEGER PRIMARY KEY, usuario_id INTEGER, nombre TEXT,
        key_hash TEXT, key_prefix TEXT, scopes TEXT,
        activo BOOLEAN DEFAULT 1, ultimo_uso TIMESTAMP, created_at TIMESTAMP
    )
"""))

db.add(Usuario(id=7, nombre="Thomas", email="thomas@unergy.io",
               password_hash="x", rol="operaciones", activo=True))
db.execute(text("INSERT INTO api_keys (id, usuario_id, nombre, key_hash, key_prefix, activo) "
                "VALUES (1, 7, 'Integracion Thomas', :h, 'uop_a1b2', 1)"), {"h": HASH})

for i, (cod, et, orden, fin) in enumerate([
    ("programado", "Programado", 0, False), ("abierta", "Abierta", 1, False),
    ("en_gestion", "En gestión", 2, False), ("en_espera", "En espera", 3, False),
    ("cerrada", "Cerrada", 4, True), ("sin_solucion", "Sin solución", 5, True),
], start=1):
    db.add(FallaCatEstado(id=i, codigo=cod, etiqueta=et, orden=orden, es_estado_final=fin))
db.add(FallaCatPrioridad(id=1, codigo="alta", etiqueta="Alta", nivel=3))
db.add(Proyecto(id=10, nombre_comercial="Santa Fe 2", sub_project="SF2",
                estado="en_operacion", municipio="Sincelejo", departamento="Sucre",
                potencia_instalada_kwp=990))
db.flush()
for n, estado_id in enumerate([2, 3, 4, 1, 5, 6], start=1):
    db.add(Falla(id=n, codigo_interno=f"FAL-2026-{n:05d}", proyecto_id=10,
                 estado_id=estado_id, prioridad_id=1, registrado_por_id=7,
                 descripcion=f"prueba {n}", fecha_identificacion=HOY - dt.timedelta(days=n),
                 fecha_programada=HOY + dt.timedelta(days=3) if estado_id == 1 else None))
db.commit()

app = FastAPI()
app.include_router(api_router)          # el router REAL, con la auth REAL
app.dependency_overrides[get_db] = lambda: db
c = TestClient(app)

URL = "/api/v1/fallas/por-proyecto"
fallos = []


def check(nombre, cond, extra=""):
    print(("  OK   " if cond else "  FALLA") + f"  {nombre}{'  ' + extra if extra else ''}")
    if not cond:
        fallos.append(nombre)


print("\n1) La ruta exige autenticacion")
r = c.get(URL, params={"proyecto_id": 10})
check("sin credenciales -> 401", r.status_code == 401, f"(dio {r.status_code})")
r = c.get(URL, params={"proyecto_id": 10}, headers={"X-API-Key": "uop_" + "0" * 64})
check("API Key falsa -> 401", r.status_code == 401, f"(dio {r.status_code})")

print("\n2) Con la API Key de Thomas")
H = {"X-API-Key": CLAVE}
r = c.get(URL, params={"proyecto_id": 10}, headers=H)
check("vigente (default) -> 200", r.status_code == 200, f"(dio {r.status_code}) {r.text[:200]}")
b = r.json()
check("trae 3 vigentes", b["total"] == 3, f"(trajo {b['total']})")
check("resumen completo", b["resumen"] == {"vigente": 3, "programado": 1, "terminado": 2, "total": 6},
      str(b["resumen"]))

for grupo, esperado in (("programado", 1), ("terminado", 2), ("todas", 6)):
    b = c.get(URL, params={"proyecto_id": 10, "estado": grupo}, headers=H).json()
    check(f"estado={grupo} -> {esperado}", b["total"] == esperado, f"(trajo {b['total']})")

b = c.get(URL, params={"api_id_unergy": "SF2", "estado": "todas"}, headers=H).json()
check("por api_id_unergy", b["proyecto"]["id"] == 10 and b["total"] == 6)
b = c.get(URL, params={"nombre": "santa fe 2", "estado": "todas"}, headers=H).json()
check("por nombre (sin tildes/mayus)", b["proyecto"]["id"] == 10 and b["total"] == 6)

print("\n3) La API Key registra su uso")
uso = db.execute(text("SELECT ultimo_uso FROM api_keys WHERE id = 1")).scalar()
check("ultimo_uso quedo estampado", uso is not None, str(uso))

print("\n4) Muestra de la respuesta")
b = c.get(URL, params={"proyecto_id": 10, "estado": "programado"}, headers=H).json()
import json
print(json.dumps({k: b[k] for k in ("proyecto", "estado_consultado", "estados_incluidos",
                                    "resumen", "total")}, indent=2, ensure_ascii=False))
print(json.dumps(b["items"][0], indent=2, ensure_ascii=False))

print("\n" + ("TODO EN VERDE" if not fallos else f"FALLARON: {fallos}"))
raise SystemExit(1 if fallos else 0)
