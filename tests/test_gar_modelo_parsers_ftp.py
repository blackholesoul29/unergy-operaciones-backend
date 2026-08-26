"""Parseo de los insumos horarios anchos de XM a formato largo.

Los bytes de los fixtures son recortes de archivos reales. El encoding latin1 no es
decorativo: los BalCttos reales fallan en utf-8 por la tilde de PÉRDIDAS.

Los cuatro parsers devuelven `(filas, descartadas)`: `descartadas` cuenta las filas
que se dropearon por venir truncadas (menos columnas de las esperadas). No se lanza
excepción — una fila malformada no debe abortar todo el archivo — pero el conteo
tiene que llegar a quien llama, porque una fila truncada que borra justo el concepto
`NETO DE COMPRAS EN BOLSA` es indistinguible, río abajo, de "no hubo exposición".
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
    filas, descartadas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 4 * 24
    assert descartadas == 0


def test_balcttos_normaliza_el_concepto_con_tilde():
    filas, _ = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    conceptos = {f["concepto"] for f in filas}
    assert "perdidas asignadas a un generador" in conceptos


def test_balcttos_conserva_el_concepto_crudo():
    filas, _ = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    crudos = {f["concepto_raw"] for f in filas}
    assert "PÉRDIDAS ASIGNADAS A UN GENERADOR" in crudos


def test_balcttos_hora_va_de_1_a_24():
    filas, _ = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    horas = sorted({f["hora"] for f in filas})
    assert horas == list(range(1, 25))


def test_balcttos_marca_fecha_version_y_entidad():
    filas, _ = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    f = filas[0]
    assert f["fecha_documento"] == FECHA
    assert f["version"] == "tx2"
    assert f["entidad"] == "UNGG"
    assert f["tipo"] == "balcttos"


def test_balcttos_fila_truncada_se_descarta_y_se_cuenta():
    # Antes de la fix, una fila con menos columnas de las esperadas se perdía con
    # un `continue` mudo: `validar_estructura` solo mira la cabecera, así que el
    # archivo pasaba validación y la fila se esfumaba sin que nadie se enterara.
    truncada = BALCTTOS + b"NETO DE COMPRAS EN BOLSA;NACIONAL;;;;;;1;2;3\n"
    filas, descartadas = parsear_balcttos(truncada, FECHA, "tx2", "UNGG")
    assert descartadas == 1
    assert len(filas) == 4 * 24  # la fila truncada no se agrega


def test_trsd_extrae_pbna_por_hora():
    filas, _ = parsear_trsd(TRSD, FECHA, "tx2")
    filas = [f for f in filas if f["concepto"] == "pbna"]
    assert len(filas) == 24
    assert all(f["valor"] == 250.5 for f in filas)


def test_trsd_entidad_es_nacional():
    filas, _ = parsear_trsd(TRSD, FECHA, "tx2")
    assert filas[0]["entidad"] == "NACIONAL"


def test_parsers_toleran_utf8_sig():
    # El mismo contenido en utf-8 con BOM debe dar el mismo resultado.
    utf8 = BALCTTOS.decode("latin1").encode("utf-8-sig")
    filas, descartadas = parsear_balcttos(utf8, FECHA, "tx2", "UNGG")
    assert len(filas) == 4 * 24
    assert descartadas == 0


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

# Desde 2026-03-08 XM antepone AGENTE a la cabecera de arrpas (Hallazgo D). El
# antiguo `parsear_arrpas` tomaba siempre col[0] como submercado, así que en este
# layout leía el AGENTE como si fuera el submercado.
ARRPAS_CON_AGENTE = (
    "AGENTE;SUBMERCADO;DELN $/KWH;VRA $;VDA $\n"
    "GENX;3A44;3.56;35243.84;0\n"
    "GENY;3HYG;3.56;4379.04;0\n"
).encode("latin1")


def test_dspcttos_filtra_a_las_filas_del_agente():
    filas, _ = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert {f["entidad"] for f in filas} == {"78596"}


def test_dspcttos_solo_ingiere_el_bloque_de_despacho():
    # La tarifa (400) no entra: no forma parte de la identidad de exposición.
    filas, _ = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 24
    assert all(f["valor"] == 50 for f in filas)
    assert {f["concepto"] for f in filas} == {"despacho"}


def test_dspcttos_fila_truncada_se_descarta_y_se_cuenta():
    truncada = DSPCTTOS + b"11111;UNGG;TPLC;PC;N;NB;1;2;3\n"
    filas, descartadas = parsear_dspcttos(truncada, FECHA, "tx2", "UNGG")
    assert descartadas == 1
    assert {f["entidad"] for f in filas} == {"78596"}


def test_arrpas_usa_el_centinela_cero_en_hora():
    # `hora` es NOT NULL: con NULL, Postgres no dedupe (NULL != NULL en un UNIQUE)
    # y las medidas no horarias se duplicarían en silencio. 0 = no horaria.
    filas, _ = parsear_arrpas(ARRPAS, FECHA, "tx2")
    assert all(f["hora"] == 0 for f in filas)
    assert {f["entidad"] for f in filas} == {"3A44", "3HYG"}


def test_arrpas_usa_la_cabecera_como_concepto():
    filas, _ = parsear_arrpas(ARRPAS, FECHA, "tx2")
    conceptos = {f["concepto"] for f in filas}
    assert "vra $" in conceptos
    vra = [f for f in filas if f["concepto"] == "vra $" and f["entidad"] == "3A44"]
    assert vra[0]["valor"] == 35243.84


def test_arrpas_fila_truncada_se_descarta_y_se_cuenta():
    truncada = ARRPAS + b"SOLO_SUBMERCADO\n"
    filas, descartadas = parsear_arrpas(truncada, FECHA, "tx2")
    assert descartadas == 1
    assert {f["entidad"] for f in filas} == {"3A44", "3HYG"}


def test_arrpas_detecta_layout_con_agente_y_usa_submercado_como_entidad():
    # Prueba directa del Hallazgo D: con AGENTE antepuesto, la entidad debe seguir
    # siendo el SUBMERCADO (columna 1), no el AGENTE (columna 0).
    filas, descartadas = parsear_arrpas(ARRPAS_CON_AGENTE, FECHA, "tx2")
    assert descartadas == 0
    assert {f["entidad"] for f in filas} == {"3A44", "3HYG"}
    vra = [f for f in filas if f["concepto"] == "vra $" and f["entidad"] == "3A44"]
    assert vra[0]["valor"] == 35243.84


def test_arrpas_con_agente_no_agrega_columna_de_agente_al_esquema():
    # El agente se descarta deliberadamente (no se pidió preservarlo): cada fila
    # solo trae las claves usuales, sin ningún campo nuevo para el agente.
    filas, _ = parsear_arrpas(ARRPAS_CON_AGENTE, FECHA, "tx2")
    claves_esperadas = {"tipo", "fecha_documento", "hora", "entidad", "concepto",
                         "concepto_raw", "valor", "version"}
    assert set(filas[0].keys()) == claves_esperadas
