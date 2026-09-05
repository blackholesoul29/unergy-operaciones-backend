"""Datos geográficos del mapa de fallas, leídos de DOS bases externas.

`requestsdb` trae circuitos y subestaciones (esquema `management_*`) y
`originabotdb` las minigranjas (`minifarm_project`). Las dos son de OTROS
servicios y se leen en solo lectura.

`ponytail: psycopg crudo, no una segunda base en DATABASES`. Declarar modelos
Django `managed = False` para dos esquemas ajenos —que además usan PostGIS y
cambian sin avisarnos— sería mucho código para tres consultas de solo lectura, y
nos ataría a su forma. Si algún día hay que escribir en ellas o las consultas se
multiplican, ahí sí vale un router de base de datos.
"""

import re
from contextlib import contextmanager

import psycopg
from django.conf import settings

# Solo letras, dígitos, espacios, guion y guion bajo: el código del operador
# entra en la consulta como parámetro, pero se valida igual para no aceptar
# basura que solo puede ser un error del cliente.
OPERADOR_VALIDO = re.compile(r"^[a-z0-9 _\-]+$", re.IGNORECASE)


def _normalizar_url(url: str) -> str:
    """Deja la URL en el esquema que acepta psycopg3 (`postgresql://`).

    Cubre el esquema con driver de SQLAlchemy (`postgresql+psycopg://`) y el
    `postgres://` que emiten Railway/Heroku: psycopg3 rechaza el segundo, así
    que una URL de Railway sin normalizar no conecta.
    """
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@contextmanager
def _conexion(url: str):
    """Cede `None` si la URL no está configurada, en vez de fallar.

    Un entorno sin estas bases (local, CI) debe poder llamar al endpoint y
    recibir listas vacías.
    """
    if not url:
        yield None
        return
    conexion = psycopg.connect(_normalizar_url(url), autocommit=True)
    try:
        yield conexion
    finally:
        conexion.close()


def _requestsdb():
    return _conexion(getattr(settings, "REQUESTSDB_DATABASE_URL", ""))


def _originadb():
    return _conexion(getattr(settings, "ORIGINA_DATABASE_URL", ""))


def operadores() -> list[dict]:
    """Operadores de red disponibles en requestsdb."""
    with _requestsdb() as conexion:
        if conexion is None:
            return []
        filas = conexion.execute(
            "SELECT code, name FROM management_gridoperator ORDER BY name"
        ).fetchall()
    return [{"code": f[0], "name": f[1]} for f in filas]


def mapa(operador: str) -> dict:
    """Subestaciones, líneas de circuito (GeoJSON) y minigranjas de un operador."""
    subestaciones, lineas, minigranjas = [], [], []

    with _requestsdb() as conexion:
        if conexion is not None:
            subestaciones = _subestaciones(conexion, operador)
            lineas = _lineas_de_circuito(conexion, operador)

    with _originadb() as conexion:
        if conexion is not None:
            minigranjas = _minigranjas(conexion, operador)

    return {
        "substations": subestaciones,
        "minigranjas": minigranjas,
        "circuitLines": lineas,
    }


def _subestaciones(conexion, operador: str) -> list[dict]:
    filas = conexion.execute("""
        SELECT DISTINCT s.id, s.name,
          ST_Y(s.geometry::geometry) AS lat,
          ST_X(s.geometry::geometry) AS lng,
          s.capacity138, s.capacity345,
          COUNT(DISTINCT c.id) AS circuit_count
        FROM management_substation s
        JOIN management_substation_circuits sc ON sc.substation_id = s.id
        JOIN management_circuit c ON sc.circuit_id = c.id
        WHERE c.grid_operator_id = %s
        GROUP BY s.id, s.name, s.geometry, s.capacity138, s.capacity345
    """, (operador,)).fetchall()
    # Se descartan las que no tienen coordenadas: el mapa no puede dibujarlas.
    return [
        {
            "id": f[0], "name": f[1],
            "lat": float(f[2]), "lng": float(f[3]),
            "capacity138": float(f[4] or 0),
            "capacity345": float(f[5] or 0),
            "circuit_count": int(f[6]),
        }
        for f in filas if f[2] and f[3]
    ]


def _lineas_de_circuito(conexion, operador: str) -> list[dict]:
    filas = conexion.execute("""
        SELECT c.id, c.name, c.tension_level,
          string_agg(DISTINCT s.name, ' / ' ORDER BY s.name) AS substation_name,
          ST_AsGeoJSON(ml.geometry) AS geojson
        FROM management_multilinegeometry ml
        JOIN management_circuit c ON ml.circuit_id = c.id
        LEFT JOIN management_substation_circuits sc ON sc.circuit_id = c.id
        LEFT JOIN management_substation s ON sc.substation_id = s.id
        WHERE c.grid_operator_id = %s
        GROUP BY c.id, c.name, c.tension_level, ml.geometry
    """, (operador,)).fetchall()
    return [
        {
            "circuit_id": f[0],
            "circuit_name": f[1],
            # 13.2 kV es el nivel por defecto de la red de distribución.
            "tension_level": float(f[2] or 13.2),
            "substation_name": f[3],
            "geojson": f[4],
        }
        for f in filas if f[4]
    ]


def _minigranjas(conexion, operador: str) -> list[dict]:
    filas = conexion.execute("""
        SELECT id, name, circuit AS circuit_name,
               project_installed_power AS kwp, lat, lng
        FROM minifarm_project
        WHERE grid_operator_id = %s AND stage = 'operation'
          AND lat IS NOT NULL AND lng IS NOT NULL
        LIMIT 500
    """, (operador,)).fetchall()
    return [
        {
            "id": f[0], "name": f[1], "circuit_name": f[2],
            "kwp": float(f[3] or 0),
            "lat": float(f[4]), "lng": float(f[5]),
        }
        for f in filas
    ]
