"""Tests del filtrado de archivos de ER (función pura, sin tocar Drive).

El mismo filtro alimenta el listado y la descarga masiva, así que tiene que dar
exactamente el mismo conjunto en ambos casos: si divergen, el ZIP traería
archivos distintos a los que el usuario ve en la tabla.
"""
from app.services.drive import filtrar_archivos


def _a(name, tipo, mes, anio, version=None):
    return {"name": name, "tipo": tipo, "mes": mes, "anio": anio, "version": version}


DATOS = [
    _a("Estado resultados Ayurá S.A.S. Puya 6 2026.xlsx", "estado_resultados", 6, 2026),
    _a("Estado resultados Ayurá S.A.S. Puya 5 2026.xlsx", "estado_resultados", 5, 2026),
    _a("Estado resultados Solenium Leyenda 6 2026.xlsx", "estado_resultados", 6, 2026),
    _a("Cruce facturas 6 2026 txf.xlsx", "cruce_facturas", 6, 2026, "txf"),
    _a("Cruce facturas 6 2026 tx3.xlsx", "cruce_facturas", 6, 2026, "tx3"),
    _a("Cruce facturas 5 2026 txf.xlsx", "cruce_facturas", 5, 2026, "txf"),
    _a("Resumen suelto.pdf", "otro", None, None),
]


def test_sin_filtros_devuelve_todo():
    assert len(filtrar_archivos(DATOS)) == len(DATOS)


def test_filtro_tipo():
    r = filtrar_archivos(DATOS, tipo="cruce_facturas")
    assert len(r) == 3
    assert all(a["tipo"] == "cruce_facturas" for a in r)


def test_filtro_periodo():
    r = filtrar_archivos(DATOS, mes=6, anio=2026)
    assert len(r) == 4


def test_filtro_version():
    r = filtrar_archivos(DATOS, version="txf")
    assert len(r) == 2
    assert all(a["version"] == "txf" for a in r)


def test_filtro_version_es_case_insensitive():
    """En los nombres reales la versión aparece en minúscula, pero el formulario
    la pide como "TXF"; el filtro no debe depender de eso."""
    assert len(filtrar_archivos(DATOS, version="TXF")) == 2


def test_filtro_texto_sobre_el_nombre():
    r = filtrar_archivos(DATOS, q="puya")
    assert len(r) == 2


def test_filtro_texto_es_case_insensitive_y_recorta_espacios():
    assert len(filtrar_archivos(DATOS, q="  PUYA ")) == 2


def test_filtros_se_combinan():
    r = filtrar_archivos(DATOS, tipo="cruce_facturas", mes=6, anio=2026, version="tx3")
    assert len(r) == 1
    assert r[0]["name"] == "Cruce facturas 6 2026 tx3.xlsx"


def test_version_no_descarta_archivos_sin_version_cuando_no_se_pide():
    """Los ER no tienen versión en el nombre: pedir tipo=ER sin versión debe
    devolverlos todos, no cero."""
    assert len(filtrar_archivos(DATOS, tipo="estado_resultados")) == 3


def test_filtro_no_muta_la_lista_original():
    antes = len(DATOS)
    filtrar_archivos(DATOS, tipo="otro")
    assert len(DATOS) == antes
