"""Parseo de los insumos horarios anchos de XM a formato largo.

Los bytes de los fixtures son recortes de archivos reales. El encoding latin1 no es
decorativo: los BalCttos reales fallan en utf-8 por la tilde de PÉRDIDAS.
"""
import datetime

from app.services.garantias_modelo.parsers_ftp import (
    parsear_arrpas,
    parsear_balcttos,
    parsear_dspcttos,
    parsear_trsd,
)

FECHA = datetime.date(2025, 12, 15)

BALCTTOS = (
    "CONCEPTO;MERCADO;CÓDIGO CONTRATO;COMPRADOR;VENDEDOR;TIPO DE DESPACHO;TIPO ASIGNA;"
    + ";".join(f"HORA {h:02d}" for h in range(1, 25)) + "\n"
    "GENERACION IDEAL;NACIONAL;;;;;;" + ";".join(["100"] * 24) + "\n"
    "NETO DE VENTAS EN BOLSA;NACIONAL;;;;;;" + ";".join(["10"] * 24) + "\n"
    "NETO DE COMPRAS EN BOLSA;NACIONAL;;;;;;" + ";".join(["4"] * 24) + "\n"
    "PÉRDIDAS ASIGNADAS A UN GENERADOR;NACIONAL;;;;;;" + ";".join(["1"] * 24) + "\n"
).encode("latin1")

TRSD = (
    "CODIGO;CONTENIDO;" + ";".join(f"HORA {h:02d}" for h in range(1, 25)) + "\n"
    "PBNA;Precio de bolsa nacional;" + ";".join(["250.5"] * 24) + "\n"
    "DMND;Demanda;" + ";".join(["9000"] * 24) + "\n"
).encode("latin1")


def test_balcttos_devuelve_una_fila_por_concepto_y_hora():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 4 * 24


def test_balcttos_normaliza_el_concepto_con_tilde():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    conceptos = {f["concepto"] for f in filas}
    assert "perdidas asignadas a un generador" in conceptos


def test_balcttos_conserva_el_concepto_crudo():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    crudos = {f["concepto_raw"] for f in filas}
    assert "PÉRDIDAS ASIGNADAS A UN GENERADOR" in crudos


def test_balcttos_hora_va_de_1_a_24():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    horas = sorted({f["hora"] for f in filas})
    assert horas == list(range(1, 25))


def test_balcttos_marca_fecha_version_y_entidad():
    f = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")[0]
    assert f["fecha_documento"] == FECHA
    assert f["version"] == "tx2"
    assert f["entidad"] == "UNGG"
    assert f["tipo"] == "balcttos"


def test_trsd_extrae_pbna_por_hora():
    filas = [f for f in parsear_trsd(TRSD, FECHA, "tx2") if f["concepto"] == "pbna"]
    assert len(filas) == 24
    assert all(f["valor"] == 250.5 for f in filas)


def test_trsd_entidad_es_nacional():
    f = parsear_trsd(TRSD, FECHA, "tx2")[0]
    assert f["entidad"] == "NACIONAL"


def test_parsers_toleran_utf8_sig():
    # El mismo contenido en utf-8 con BOM debe dar el mismo resultado.
    utf8 = BALCTTOS.decode("latin1").encode("utf-8-sig")
    assert len(parsear_balcttos(utf8, FECHA, "tx2", "UNGG")) == 4 * 24


DSPCTTOS = (
    "CONTRATO;VENDEDOR;COMPRADOR;TIPO;TIPOMERC;TIPO ASIGNA;"
    + ";".join(f"DESP_HORA {h:02d}" for h in range(1, 25)) + ";"
    + ";".join(f"TRF_HORA {h:02d}" for h in range(1, 25)) + "\n"
    "78596;UNGG;TPLC;PC;N;NB;" + ";".join(["50"] * 24) + ";" + ";".join(["400"] * 24) + "\n"
    "99999;OTRO;TPLC;PC;N;NB;" + ";".join(["70"] * 24) + ";" + ";".join(["400"] * 24) + "\n"
).encode("latin1")

ARRPAS = (
    "SUBMERCADO;DELN $/KWH;VRA $;VDA $\n"
    "3A44;3.56;35243.84;0\n"
    "3HYG;3.56;4379.04;0\n"
).encode("latin1")


def test_dspcttos_filtra_a_las_filas_del_agente():
    filas = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert {f["entidad"] for f in filas} == {"78596"}


def test_dspcttos_solo_ingiere_el_bloque_de_despacho():
    # La tarifa (400) no entra: no forma parte de la identidad de exposición.
    filas = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 24
    assert all(f["valor"] == 50 for f in filas)
    assert {f["concepto"] for f in filas} == {"despacho"}


def test_arrpas_usa_el_centinela_cero_en_hora():
    # `hora` es NOT NULL: con NULL, Postgres no dedupe (NULL != NULL en un UNIQUE)
    # y las medidas no horarias se duplicarían en silencio. 0 = no horaria.
    filas = parsear_arrpas(ARRPAS, FECHA, "tx2")
    assert all(f["hora"] == 0 for f in filas)
    assert {f["entidad"] for f in filas} == {"3A44", "3HYG"}


def test_arrpas_usa_la_cabecera_como_concepto():
    filas = parsear_arrpas(ARRPAS, FECHA, "tx2")
    conceptos = {f["concepto"] for f in filas}
    assert "vra $" in conceptos
    vra = [f for f in filas if f["concepto"] == "vra $" and f["entidad"] == "3A44"]
    assert vra[0]["valor"] == 35243.84
