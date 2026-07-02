import pandas as pd
from datetime import date

from app.services.xm.unificador import (
    encoding_para, unificar, nombre_salida, exportar, enriquecer,
)


def test_encoding_para_aenc_es_latin1():
    assert encoding_para("aenc") == "latin1"


def test_encoding_para_otros_es_utf8_sig():
    assert encoding_para("grip") == "utf-8-sig"


def _csv_bytes(texto):
    return texto.encode("utf-8-sig")


def test_unificar_agrega_fecha_como_primera_columna_y_concatena():
    archivos = [
        ("2026-05-01", _csv_bytes("PLANTA;HORA 01\n3A44;10.5\n")),
        ("2026-05-02", _csv_bytes("PLANTA;HORA 01\n3A44;11.0\n")),
    ]
    df = unificar("grip", archivos)
    assert list(df.columns)[0] == "FechaDocumento"
    assert list(df["FechaDocumento"]) == ["2026-05-01", "2026-05-02"]
    assert len(df) == 2


def test_unificar_sin_archivos_devuelve_vacio():
    df = unificar("grip", [])
    assert df.empty


def test_nombre_salida_un_solo_mes():
    xlsx, txt = nombre_salida("grip", "txf", date(2026, 5, 1), date(2026, 5, 31))
    assert xlsx == "grip_txf_05.xlsx"
    assert txt == "grip_txf_05.txf"


def test_nombre_salida_cruza_meses():
    xlsx, txt = nombre_salida("grip", "txf", date(2026, 4, 29), date(2026, 5, 2))
    assert xlsx == "grip_txf_04-05.xlsx"
    assert txt == "grip_txf_04-05.txf"


def test_exportar_devuelve_bytes_no_vacios():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    bytes_xlsx, bytes_txt = exportar(df)
    assert len(bytes_xlsx) > 0
    assert b"a;b" in bytes_txt


def test_enriquecer_agrega_columnas_y_reporta_sin_match():
    df = pd.DataFrame({
        "FechaDocumento": ["2026-05-01", "2026-05-01"],
        "PLANTA": ["3A44", "9999"],
    })
    fronteras_por_mes = {
        "2026-05": {"3A44": {"nombre": "Bayunca I", "tipo": "Generacion", "mw": 3.0}},
    }
    df2, sin_match = enriquecer(df, "grip", fronteras_por_mes, "PLANTA")
    assert df2.loc[0, "Nombre de la Frontera"] == "Bayunca I"
    assert df2.loc[0, "Capacidad efectiva [MW]"] == 3.0
    assert sin_match == {"9999"}
    assert pd.isna(df2.loc[1, "Nombre de la Frontera"])
