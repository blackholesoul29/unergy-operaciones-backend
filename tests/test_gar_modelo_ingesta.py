"""Ingesta: hash, dedup y decisión de qué entra.

No hay base de datos acá: estas pruebas llaman `preparar_archivo` directamente con
bytes en memoria y verifican el dict de metadatos que devuelve, sin tocar Postgres.
"""
import datetime

from app.services.garantias_modelo.ingesta import (
    preparar_archivo,
    sha256_de,
)

CONTENIDO = b"CODIGO;CONTENIDO;" + b";".join(
    f"HORA {h:02d}".encode() for h in range(1, 25)
) + b"\nPBNA;precio;" + b";".join([b"100"] * 24) + b"\n"


def test_sha256_es_estable():
    assert sha256_de(CONTENIDO) == sha256_de(CONTENIDO)
    assert sha256_de(CONTENIDO) != sha256_de(CONTENIDO + b"x")


TIMESTAMP = datetime.datetime(2026, 8, 26, 10, 0, tzinfo=datetime.timezone.utc)


def test_preparar_extrae_tipo_fecha_y_version():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=TIMESTAMP)
    assert r["tipo"] == "trsd"
    assert r["version"] == "tx2"
    assert r["esquema_ok"] is True
    assert r["periodo_ini"] is None          # sin `anio` no se puede fechar el archivo


def test_preparar_con_anio_resuelve_la_fecha():
    # El nombre trae MMDD sin año: el año viene de la carpeta que lo contiene.
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=TIMESTAMP, anio=2025)
    assert r["periodo_ini"] == datetime.date(2025, 12, 15)


def test_preparar_marca_esquema_invalido_sin_lanzar():
    r = preparar_archivo("trsd1215.tx2", b"CODIGO;CONTENIDO\nPBNA;x\n",
                         disponible_desde=TIMESTAMP)
    assert r["esquema_ok"] is False
    assert "motivo" in r["esquema_detalle"]


def test_preparar_observado_cuando_hay_timestamp():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=TIMESTAMP)
    assert r["origen_disponibilidad"] == "observado"
    assert r["disponible_desde"] == TIMESTAMP


# --- Hallazgo A: disponible_desde=None no debe inventar un timestamp -------------
#
# El backfill histórico no tiene forma de derivar la fecha de publicación: los zips
# del corpus no la conservan (todas las entradas traen la fecha de descarga, no la
# de publicación). Antes, `None` se estampaba silenciosamente con `now()`, lo que
# haría que TODO el backtest quedara sin datos disponibles (el filtro anti-leakage
# compara `disponible_desde <= fecha_calculo`, y con `now()` ningún `fecha_calculo`
# histórico califica jamás). La función ahora falla cerrado: rechaza el archivo en
# vez de adivinar.

def test_preparar_sin_disponible_desde_marca_esquema_invalido():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    assert r["esquema_ok"] is False
    assert "disponib" in r["esquema_detalle"]["motivo"].lower()


def test_preparar_sin_disponible_desde_no_estampa_now():
    antes = datetime.datetime.now(datetime.timezone.utc)
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    despues = datetime.datetime.now(datetime.timezone.utc)

    assert r["disponible_desde"] is None
    # Ni siquiera "cerca" de now(): no debe colarse un `now()` disfrazado de otra cosa.
    if r["disponible_desde"] is not None:
        assert not (antes <= r["disponible_desde"] <= despues)
