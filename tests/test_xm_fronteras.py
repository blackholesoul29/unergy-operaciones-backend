import io
import openpyxl

from app.services.xm.fronteras import (
    carpeta_fronteras, elegir_ultimo_archivo, parsear_fronteras_xlsx, obtener_fronteras_mes,
)


def test_carpeta_fronteras():
    assert carpeta_fronteras(2026, 5) == "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/2026-05"


def test_elegir_ultimo_archivo_ordena_por_dia():
    nombres = [
        "UNGG_FronterasComerciales_05-05-2026.xlsx",
        "UNGG_FronterasComerciales_23-05-2026.xlsx",
        "UNGG_FronterasComerciales_10-05-2026.xlsx",
        "otro_archivo.txt",
    ]
    assert elegir_ultimo_archivo(nombres) == "UNGG_FronterasComerciales_23-05-2026.xlsx"


def test_elegir_ultimo_archivo_vacio():
    assert elegir_ultimo_archivo(["algo.txt"]) is None


def _xlsx_de_prueba():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fronteras Comerciales"
    ws.append([
        "Código SIC", "Nombre de la Frontera", "Tipo de Frontera",
        "Código SIC Submercado Exportador", "Capacidad efectiva [MW]",
    ])
    ws.append(["Frt39007", "PLANTA SOLAR BAYUNCA I", "Generacion", "3A44", 3.0])
    ws.append(["Frt51338", "GRANJA SOLAR URUACO", "Generacion", "3HYG", 0.996])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parsear_fronteras_xlsx():
    tabla = parsear_fronteras_xlsx(_xlsx_de_prueba())
    assert tabla["3A44"] == {"nombre": "PLANTA SOLAR BAYUNCA I", "tipo": "Generacion", "mw": 3.0}
    assert tabla["3HYG"]["nombre"] == "GRANJA SOLAR URUACO"


def test_obtener_fronteras_mes_usa_ultimo_archivo_del_mes():
    contenido = _xlsx_de_prueba()

    def listar_fn(directorio):
        assert directorio == "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/2026-05"
        return [
            "UNGG_FronterasComerciales_05-05-2026.xlsx",
            "UNGG_FronterasComerciales_23-05-2026.xlsx",
        ]

    def descargar_fn(directorio, nombre):
        assert nombre == "UNGG_FronterasComerciales_23-05-2026.xlsx"
        return contenido

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5)
    assert mes_usado == "2026-05"
    assert archivo_usado == "UNGG_FronterasComerciales_23-05-2026.xlsx"
    assert tabla["3A44"]["mw"] == 3.0


def test_obtener_fronteras_mes_retrocede_si_mes_vacio():
    contenido = _xlsx_de_prueba()

    def listar_fn(directorio):
        if directorio.endswith("2026-05"):
            return []
        if directorio.endswith("2026-04"):
            return ["UNGG_FronterasComerciales_30-04-2026.xlsx"]
        return []

    def descargar_fn(directorio, nombre):
        return contenido

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5)
    assert mes_usado == "2026-04"
    assert archivo_usado == "UNGG_FronterasComerciales_30-04-2026.xlsx"


def test_obtener_fronteras_mes_sin_datos_devuelve_vacio():
    def listar_fn(directorio):
        return []

    def descargar_fn(directorio, nombre):
        raise AssertionError("no debería intentar descargar nada")

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5, max_retroceso=1)
    assert tabla == {}
    assert mes_usado is None
    assert archivo_usado is None
