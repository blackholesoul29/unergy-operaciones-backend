"""Parseo de los Excel de garantía, en sus dos formatos.

El nuevo (desde 2026-09-04) trae una tabla única con la ventana en columnas. El
tradicional trae una hoja por período con la ventana en el nombre de la hoja.
"""
import datetime

from app.services.garantias_modelo.parsers_garantia import (
    FORMATO_NUEVO,
    FORMATO_TRADICIONAL,
    componentes_de_hoja,
    detectar_formato,
    filas_periodos,
    ventana_de_hoja,
)

CAB_NUEVO = ("CÓDIGO", "Descripción", "Fecha Publicación", "Fecha Inicial",
             "Fecha Final", "Exposición Energía en Bolsa ($)", "Restricciones ($)",
             "Valor Garantía", "Garantías TIE", "Valor Garantía Final",
             "Estimado", "Total Ajuste")

PUB = datetime.datetime(2026, 4, 24)
I1 = datetime.datetime(2026, 4, 11)
F1 = datetime.datetime(2026, 4, 17)

FILAS_NUEVO = [
    CAB_NUEVO,
    ("AAGC", "S-1", PUB, I1, F1, 0, 0, 0, 0, 0, 0, 0),
    ("UNGG", "S-1", PUB, I1, F1, 45694583, 0, 51066768, 0, 51066768, 27532582, 23534186),
    ("UNGG", "M", PUB, datetime.datetime(2026, 4, 18), datetime.datetime(2026, 4, 30),
     65258863, 0, 75312615, 0, 75312615, 51104001, 24208614),
    ("UNGC", "S-1", PUB, I1, F1, -56734097, 0, 0, 0, 0, 0, 0),
]


def test_detectar_formato_nuevo_por_las_hojas():
    assert detectar_formato(["DEPOSITO", "PERIODOS A GARANTIZAR", "PERIODO BASE"]) == FORMATO_NUEVO


def test_detectar_formato_tradicional_por_las_hojas():
    hojas = ["DEPÓSITO SEM MENS 01 MAY", "AJUSTE PROY (M) 18-30 ABR",
             "AJUSTE TX2 SEMA MENS 11-17 ABR", "PERIODO BASE"]
    assert detectar_formato(hojas) == FORMATO_TRADICIONAL


def test_detectar_formato_no_depende_del_nombre_del_archivo():
    assert detectar_formato(["PERIODOS A GARANTIZAR"]) == FORMATO_NUEVO


def test_formato_desconocido_devuelve_none():
    assert detectar_formato(["Hoja1"]) is None


def test_filas_periodos_devuelve_una_fila_por_periodo_del_agente():
    r = filas_periodos(FILAS_NUEVO, "UNGG")
    assert len(r) == 2
    assert {x["periodo"] for x in r} == {"S-1", "M"}


def test_filas_periodos_trae_la_ventana_como_fechas():
    r = [x for x in filas_periodos(FILAS_NUEVO, "UNGG") if x["periodo"] == "S-1"][0]
    assert r["periodo_ini"] == datetime.date(2026, 4, 11)
    assert r["periodo_fin"] == datetime.date(2026, 4, 17)
    assert r["fecha_publicacion"] == datetime.date(2026, 4, 24)


def test_filas_periodos_trae_los_componentes_normalizados():
    r = [x for x in filas_periodos(FILAS_NUEVO, "UNGG") if x["periodo"] == "S-1"][0]
    assert r["componentes"]["exposicion energia en bolsa ($)"] == 45694583
    assert r["componentes"]["valor garantia"] == 51066768


def test_filas_periodos_no_mezcla_agentes():
    r = filas_periodos(FILAS_NUEVO, "UNGC")
    assert len(r) == 1
    assert r[0]["componentes"]["exposicion energia en bolsa ($)"] == -56734097


def test_filas_periodos_agente_ausente_devuelve_vacio():
    assert filas_periodos(FILAS_NUEVO, "ZZZZ") == []


def test_ventana_tx2_de_nombre_de_hoja():
    r = ventana_de_hoja("AJUSTE TX2 SEMA MENS 01-07 AGO", datetime.date(2026, 8, 28))
    assert r == (datetime.date(2026, 8, 1), datetime.date(2026, 8, 7), "AJUSTE TX2")


def test_ventana_proy_de_nombre_de_hoja():
    r = ventana_de_hoja("AJUSTE PROY (M) 08-31 AGO", datetime.date(2026, 8, 28))
    assert r[0] == datetime.date(2026, 8, 8)
    assert r[1] == datetime.date(2026, 8, 31)
    assert r[2] == "AJUSTE PROY"


def test_ventana_cruza_anio_hacia_atras():
    r = ventana_de_hoja("AJUSTE TX2 SEMA MENS 13-19 DIC", datetime.date(2026, 1, 2))
    assert r[0] == datetime.date(2025, 12, 13)
    assert r[1] == datetime.date(2025, 12, 19)


def test_hoja_sin_ventana_devuelve_none():
    assert ventana_de_hoja("PERIODO BASE", datetime.date(2026, 8, 28)) is None


def test_componentes_de_hoja_busca_la_fila_de_codigo():
    filas = [
        (None, "AJUSTE GARANTÍA", None),
        (None, "FECHA DE VENCIMIENTO: 21", None),
        ("CÓDIGO", "Exposición Energía en Bolsa ($)", "Restricciones ($)"),
        ("AAGC", 0, 0),
        ("UNGG", -107701627, 5),
    ]
    r = componentes_de_hoja(filas, "UNGG")
    assert r["exposicion energia en bolsa ($)"] == -107701627
    assert r["restricciones ($)"] == 5


def test_componentes_agente_ausente_devuelve_vacio():
    filas = [("CÓDIGO", "Exposición Energía en Bolsa ($)"), ("AAGC", 1)]
    assert componentes_de_hoja(filas, "UNGG") == {}
