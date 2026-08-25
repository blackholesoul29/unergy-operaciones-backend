"""`_ultimas_generaciones()` -- traía TODO el historial de
reporte_energia_generacion por frontera y cortaba a las últimas 3 en
Python; para una frontera con meses de corridas diarias eso eran cientos
de filas solo para quedarse con 3. Punto 14 del diagnóstico de Fronteras,
2026-08-25: reescrito con ROW_NUMBER() en SQL (ver CORRIDAS_VENTANA_GENERANDO
en app/api/v1/fronteras.py) para traer solo el top-N por frontera.

Esta prueba confirma que el resultado es el mismo de antes: exactamente
las CORRIDAS_VENTANA_GENERANDO filas más recientes (por fecha desc) por
cada frontera, particionado correctamente entre varias fronteras."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.api.v1.fronteras import _ultimas_generaciones, CORRIDAS_VENTANA_GENERANDO


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


def _agregar_corridas(db, frontera_id, n_dias, id_inicial):
    """Crea n_dias corridas consecutivas terminando hoy, una por día,
    con id creciente en el mismo orden que la fecha (más reciente = id más
    alto), para poder distinguir sin ambigüedad cuáles debieron sobrevivir."""
    hoy = dt.date(2026, 8, 25)
    ids = []
    for i in range(n_dias):
        fecha = hoy - dt.timedelta(days=n_dias - 1 - i)
        gen_id = id_inicial + i
        db.add(ReporteEnergiaGeneracion(
            id=gen_id, frontera_id=frontera_id, fecha=fecha, caso=1,
            energia_final_kwh=100 + i,
        ))
        ids.append((fecha, gen_id))
    return ids


def test_devuelve_solo_las_n_mas_recientes_por_frontera(db):
    proy = Proyecto(id=1, nombre_comercial="Planta Test")
    db.add(proy)
    f1 = Frontera(id=1, proyecto_id=1, nombre_frontera="F1", codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    db.add(f1)
    db.commit()

    # 10 corridas diarias para una sola frontera -- muchas más que la ventana.
    _agregar_corridas(db, frontera_id=1, n_dias=10, id_inicial=100)
    db.commit()

    resultado = _ultimas_generaciones(db, [1])

    assert set(resultado.keys()) == {1}
    filas = resultado[1]
    assert len(filas) == CORRIDAS_VENTANA_GENERANDO

    # Deben ser exactamente las 3 fechas más recientes (2026-08-23/24/25),
    # es decir los ids más altos (109, 108, 107) -- no las más antiguas.
    ids_obtenidos = sorted(f.id for f in filas)
    assert ids_obtenidos == [107, 108, 109]
    fechas_obtenidas = sorted(f.fecha for f in filas)
    assert fechas_obtenidas == [dt.date(2026, 8, 23), dt.date(2026, 8, 24), dt.date(2026, 8, 25)]


def test_particiona_correctamente_entre_varias_fronteras(db):
    proy = Proyecto(id=1, nombre_comercial="Planta Test")
    db.add(proy)
    f1 = Frontera(id=1, proyecto_id=1, nombre_frontera="F1", codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    f2 = Frontera(id=2, proyecto_id=1, nombre_frontera="F2", codigo_frontera="frt00002", tipo_frontera="generacion", estado="activa")
    f3 = Frontera(id=3, proyecto_id=1, nombre_frontera="F3", codigo_frontera="frt00003", tipo_frontera="generacion", estado="activa")
    db.add_all([f1, f2, f3])
    db.commit()

    # Fronteras con historiales de tamaño distinto -- una con menos días que
    # la ventana (no debe fallar ni traer de más).
    _agregar_corridas(db, frontera_id=1, n_dias=10, id_inicial=100)
    _agregar_corridas(db, frontera_id=2, n_dias=2, id_inicial=200)
    _agregar_corridas(db, frontera_id=3, n_dias=5, id_inicial=300)
    db.commit()

    resultado = _ultimas_generaciones(db, [1, 2, 3])

    assert set(resultado.keys()) == {1, 2, 3}
    assert len(resultado[1]) == CORRIDAS_VENTANA_GENERANDO
    assert len(resultado[2]) == 2  # menos corridas que la ventana -- trae todas
    assert len(resultado[3]) == CORRIDAS_VENTANA_GENERANDO

    assert sorted(f.id for f in resultado[1]) == [107, 108, 109]
    assert sorted(f.id for f in resultado[2]) == [200, 201]
    assert sorted(f.id for f in resultado[3]) == [302, 303, 304]

    # Ninguna fila de una frontera se coló en el resultado de otra.
    for fid, filas in resultado.items():
        assert all(f.frontera_id == fid for f in filas)


def test_frontera_sin_corridas_no_aparece_en_el_resultado(db):
    proy = Proyecto(id=1, nombre_comercial="Planta Test")
    db.add(proy)
    f1 = Frontera(id=1, proyecto_id=1, nombre_frontera="F1", codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    db.add(f1)
    db.commit()

    resultado = _ultimas_generaciones(db, [1])

    assert resultado == {}


def test_lista_vacia_de_fronteras_no_consulta_nada(db):
    assert _ultimas_generaciones(db, []) == {}
