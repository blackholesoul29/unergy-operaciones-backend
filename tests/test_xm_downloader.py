from datetime import date
from app.services.xm.downloader import ejecutar_descarga


def test_descarga_exitosa_sin_reintentos():
    llamadas = []

    def conectar_fn(host, usuario, clave, directorio):
        return {"directorio": directorio}

    def descargar_fn(ftp, nombre):
        llamadas.append(nombre)
        return b"contenido"

    archivos, faltantes = ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 2),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
    )
    assert llamadas == ["grip0501.txf", "grip0502.txf"]
    assert archivos == [("2026-05-01", b"contenido"), ("2026-05-02", b"contenido")]
    assert faltantes == []


def test_descarga_agota_reintentos_y_reporta_faltante():
    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        raise Exception("archivo no existe")

    archivos, faltantes = ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 1),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        max_reintentos=2, sleep_fn=lambda s: None,
    )
    assert archivos == []
    assert faltantes == ["grip0501.txf"]


def test_descarga_reporta_progreso():
    progresos = []

    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        return b"x"

    ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 3),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        on_progreso=lambda hechos, total: progresos.append((hechos, total)),
    )
    assert progresos == [(1, 3), (2, 3), (3, 3)]
