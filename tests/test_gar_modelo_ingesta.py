"""Ingesta: hash, dedup y decisión de qué entra. Sin base de datos: la función
recibe un callable para consultar si el hash ya existe."""
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


def test_preparar_extrae_tipo_fecha_y_version():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    assert r["tipo"] == "trsd"
    assert r["version"] == "tx2"
    assert r["esquema_ok"] is True
    assert r["periodo_ini"] is None          # sin `anio` no se puede fechar el archivo


def test_preparar_con_anio_resuelve_la_fecha():
    # El nombre trae MMDD sin año: el año viene de la carpeta que lo contiene.
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None, anio=2025)
    assert r["periodo_ini"] == datetime.date(2025, 12, 15)


def test_preparar_marca_esquema_invalido_sin_lanzar():
    r = preparar_archivo("trsd1215.tx2", b"CODIGO;CONTENIDO\nPBNA;x\n", disponible_desde=None)
    assert r["esquema_ok"] is False
    assert "motivo" in r["esquema_detalle"]


def test_preparar_derivado_cuando_no_hay_timestamp():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    assert r["origen_disponibilidad"] == "derivado"


def test_preparar_observado_cuando_hay_timestamp():
    t = datetime.datetime(2026, 8, 26, 10, 0, tzinfo=datetime.timezone.utc)
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=t)
    assert r["origen_disponibilidad"] == "observado"
    assert r["disponible_desde"] == t
