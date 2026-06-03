"""
Mapa OR — expone datos geográficos de circuitos, subestaciones y
minigranjas para el mapa de fallas. Lee desde las DBs externas
(requestsdb + originabotdb) de forma read-only.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

router = APIRouter(prefix="/mapa", tags=["Mapa"])


def _fix_url(url: str) -> str:
    """Normalize a DB URL to the scheme psycopg3 accepts (`postgresql://`).

    Handles the SQLAlchemy driver scheme (`postgresql+psycopg://`) and the bare
    `postgres://` that Railway/Heroku emit for DATABASE_URL — psycopg3 rejects the
    latter, so an unnormalized Railway URL would fail to connect.
    """
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@contextmanager
def _rconn():
    if not settings.REQUESTSDB_DATABASE_URL:
        yield None
        return
    conn = psycopg.connect(_fix_url(settings.REQUESTSDB_DATABASE_URL), autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _oconn():
    if not settings.ORIGINA_DATABASE_URL:
        yield None
        return
    conn = psycopg.connect(_fix_url(settings.ORIGINA_DATABASE_URL), autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@router.get("/operadores")
def get_operadores() -> list[dict]:
    """Lista operadores de red disponibles en requestsdb."""
    with _rconn() as conn:
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT code, name FROM management_gridoperator ORDER BY name"
        ).fetchall()
        return [{"code": r[0], "name": r[1]} for r in rows]


@router.get("")
def get_mapa(operator: str = Query(..., min_length=1, max_length=50)) -> dict[str, Any]:
    """
    Retorna circuitos (GeoJSON), subestaciones y minigranjas para el mapa.
    """
    if not re.match(r"^[a-z0-9 _\-]+$", operator, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Operador inválido")

    substations: list[dict] = []
    minigranjas: list[dict] = []
    circuit_lines: list[dict] = []

    with _rconn() as conn:
        if conn is not None:
            # ── Subestaciones ───────────────────────────────────────────────
            rows = conn.execute("""
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
            """, (operator,)).fetchall()

            substations = [
                {
                    "id": r[0], "name": r[1],
                    "lat": float(r[2]), "lng": float(r[3]),
                    "capacity138": float(r[4] or 0),
                    "capacity345": float(r[5] or 0),
                    "circuit_count": int(r[6]),
                }
                for r in rows if r[2] and r[3]
            ]

            # ── Líneas de circuito con geometría GeoJSON ────────────────────
            rows = conn.execute("""
                SELECT c.id, c.name, c.tension_level,
                  string_agg(DISTINCT s.name, ' / ' ORDER BY s.name) AS substation_name,
                  ST_AsGeoJSON(ml.geometry) AS geojson
                FROM management_multilinegeometry ml
                JOIN management_circuit c ON ml.circuit_id = c.id
                LEFT JOIN management_substation_circuits sc ON sc.circuit_id = c.id
                LEFT JOIN management_substation s ON sc.substation_id = s.id
                WHERE c.grid_operator_id = %s
                GROUP BY c.id, c.name, c.tension_level, ml.geometry
            """, (operator,)).fetchall()

            circuit_lines = [
                {
                    "circuit_id": r[0],
                    "circuit_name": r[1],
                    "tension_level": float(r[2] or 13.2),
                    "substation_name": r[3],
                    "geojson": r[4],
                }
                for r in rows if r[4]
            ]

    with _oconn() as conn:
        if conn is not None:
            # ── Proyectos/minigranjas con coordenadas ───────────────────────
            rows = conn.execute("""
                SELECT id, name, circuit AS circuit_name,
                       project_installed_power AS kwp, lat, lng
                FROM minifarm_project
                WHERE grid_operator_id = %s AND stage = 'operation'
                  AND lat IS NOT NULL AND lng IS NOT NULL
                LIMIT 500
            """, (operator,)).fetchall()

            minigranjas = [
                {
                    "id": r[0], "name": r[1],
                    "circuit_name": r[2],
                    "kwp": float(r[3] or 0),
                    "lat": float(r[4]), "lng": float(r[5]),
                }
                for r in rows
            ]

    return {
        "substations": substations,
        "minigranjas": minigranjas,
        "circuitLines": circuit_lines,
    }
