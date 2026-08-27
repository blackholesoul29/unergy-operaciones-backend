"""GET /fronteras -- los contactos CGM del proyecto se consultaban una vez
POR FRONTERA en vez de una vez por proyecto, sin deduplicar cuando varias
fronteras (típico: generación + consumo de la misma planta) comparten
proyecto_id -- punto 13 del diagnóstico de Fronteras, 2026-08-25."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.fronteras import Frontera
from app.api.v1 import fronteras as api


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


def _contar_queries(db, fn):
    contador = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*args, **kwargs):
        contador["n"] += 1

    resultado = fn()
    return resultado, contador["n"]


def test_fronteras_del_mismo_proyecto_no_repiten_la_consulta_de_contactos(db):
    cli = Cliente(id=1, razon_social_nombre="INVERSIONES TEST S.A.S.")
    db.add(cli)
    proy = Proyecto(id=1, nombre_comercial="Planta Compartida")
    db.add(proy)
    db.add(ProyectoInversionista(id=1, proyecto_id=1, cliente_id=1, porcentaje_participacion=100))
    db.add(Contacto(id=1, cliente_id=1, email="cgm@test.com", tipo="cgm"))
    db.flush()

    # 5 fronteras del MISMO proyecto (ej. generación, consumo, y sus
    # variantes) -- antes esto disparaba la consulta de contactos 5 veces.
    for i in range(5):
        db.add(Frontera(
            id=i + 1, proyecto_id=1, nombre_frontera=f"Frontera {i}",
            codigo_frontera=f"frt{i:05d}", tipo_frontera="generacion", estado="activa",
        ))
    db.commit()

    resultado, con_5_fronteras = _contar_queries(
        db, lambda: api.list_fronteras(
            proyecto_id=None, tipo_frontera=None, estado=None, incluir_clientes_cgm=True,
            skip=0, limit=100, db=db, _=ADMIN,
        ),
    )

    assert len(resultado) == 5
    for f in resultado:
        assert f.clientes_cgm == [{"id": 1, "nombre": "INVERSIONES TEST S.A.S.", "correos": ["cgm@test.com"]}]

    # Ahora con 10 fronteras del mismo proyecto -- si la consulta de
    # contactos estuviera deduplicada por proyecto (no por fila), el número
    # de queries NO debería crecer proporcional a la cantidad de fronteras.
    for i in range(5, 10):
        db.add(Frontera(
            id=i + 1, proyecto_id=1, nombre_frontera=f"Frontera {i}",
            codigo_frontera=f"frt{i:05d}", tipo_frontera="generacion", estado="activa",
        ))
    db.commit()

    resultado_10, con_10_fronteras = _contar_queries(
        db, lambda: api.list_fronteras(
            proyecto_id=None, tipo_frontera=None, estado=None, incluir_clientes_cgm=True,
            skip=0, limit=100, db=db, _=ADMIN,
        ),
    )

    assert len(resultado_10) == 10
    assert con_10_fronteras == con_5_fronteras, (
        f"{con_5_fronteras} consultas con 5 fronteras y {con_10_fronteras} con 10 "
        f"(mismo proyecto en ambos casos): hay N+1 por fila en vez de por proyecto"
    )


def test_sin_incluir_clientes_cgm_no_paga_ninguna_consulta_extra(db):
    """Auditoría de eficiencia 2026-08-26: clientes_cgm solo lo leen 3 vistas
    de Reporte CGM -- el catálogo de Fronteras y otras 5 vistas llamaban a
    GET /fronteras sin usarlo nunca, pagando igual ~2 queries por proyecto +
    1 por cliente distinto. Ahora es opt-in (incluir_clientes_cgm=True);
    sin el flag, clientes_cgm queda en [] sin ninguna consulta extra."""
    cli = Cliente(id=1, razon_social_nombre="INVERSIONES TEST S.A.S.")
    db.add(cli)
    proy = Proyecto(id=1, nombre_comercial="Planta Compartida")
    db.add(proy)
    db.add(ProyectoInversionista(id=1, proyecto_id=1, cliente_id=1, porcentaje_participacion=100))
    db.add(Contacto(id=1, cliente_id=1, email="cgm@test.com", tipo="cgm"))
    db.add(Frontera(
        id=1, proyecto_id=1, nombre_frontera="Frontera 0",
        codigo_frontera="frt00000", tipo_frontera="generacion", estado="activa",
    ))
    db.commit()

    resultado, con_flag = _contar_queries(
        db, lambda: api.list_fronteras(
            proyecto_id=None, tipo_frontera=None, estado=None, incluir_clientes_cgm=True,
            skip=0, limit=100, db=db, _=ADMIN,
        ),
    )
    resultado_sin, sin_flag = _contar_queries(
        db, lambda: api.list_fronteras(
            proyecto_id=None, tipo_frontera=None, estado=None, incluir_clientes_cgm=False,
            skip=0, limit=100, db=db, _=ADMIN,
        ),
    )

    assert resultado[0].clientes_cgm == [{"id": 1, "nombre": "INVERSIONES TEST S.A.S.", "correos": ["cgm@test.com"]}]
    assert resultado_sin[0].clientes_cgm == []
    assert sin_flag < con_flag, "sin el flag debería pagar menos queries que con él"
