from datetime import date
from app.services.xm.downloader import ejecutar_descarga


def _sin_cache(**overrides):
    """Todas las pruebas de red pasan usar_cache=False para no tocar el
    disco real (la caché tiene sus propios tests en test_xm_downloader
    con cache_leer_fn/cache_guardar_fn falsos)."""
    base = {"usar_cache": False}
    base.update(overrides)
    return base


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
        conectar_fn=conectar_fn, descargar_fn=descargar_fn, **_sin_cache(),
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
        max_reintentos=2, sleep_fn=lambda s: None, **_sin_cache(),
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
        on_progreso=lambda hechos, total: progresos.append((hechos, total)), **_sin_cache(),
    )
    assert progresos == [(1, 3), (2, 3), (3, 3)]


def test_descarga_usa_cache_y_no_llama_ftp_si_hay_hit():
    llamadas_ftp = []
    llamadas_conectar = []

    def conectar_fn(host, usuario, clave, directorio):
        llamadas_conectar.append(directorio)
        return object()

    def descargar_fn(ftp, nombre):
        llamadas_ftp.append(nombre)
        return b"de la red"

    def cache_leer_fn(anio, nombre_archivo):
        return b"de la cache" if nombre_archivo == "grip0501.txf" else None

    archivos, faltantes = ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 2),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        cache_leer_fn=cache_leer_fn, cache_guardar_fn=lambda *a: None,
    )
    # El día 1 vino de la caché (no llamó FTP); el día 2 sí, porque no había cache hit.
    assert llamadas_ftp == ["grip0502.txf"]
    assert archivos == [("2026-05-01", b"de la cache"), ("2026-05-02", b"de la red")]
    assert faltantes == []
    # Ni siquiera conectó al FTP para el archivo que vino de caché — solo
    # conecta cuando efectivamente necesita descargar algo.
    assert llamadas_conectar == ["/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"]


def test_descarga_guarda_en_cache_lo_que_descarga_de_la_red():
    guardados = []

    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        return b"contenido"

    ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 1),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        cache_leer_fn=lambda anio, nombre: None,
        cache_guardar_fn=lambda anio, nombre, contenido: guardados.append((anio, nombre, contenido)),
    )
    assert guardados == [(2026, "grip0501.txf", b"contenido")]


def test_descarga_no_guarda_en_cache_si_usar_cache_es_falso():
    guardados = []

    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        return b"contenido"

    ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 1),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn, usar_cache=False,
        cache_guardar_fn=lambda anio, nombre, contenido: guardados.append((anio, nombre, contenido)),
    )
    assert guardados == []
