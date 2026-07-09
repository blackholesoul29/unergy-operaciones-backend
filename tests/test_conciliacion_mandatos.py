"""Tests del motor puro de conciliación Mandato (PDF) vs. Asiento (Excel Odoo).

Mirror en backend de src/utils/conciliacionMandatos.test.mjs del frontend.
Cubre el criterio STRADA/ESTRADA, el neteo de arriendo (suma de débitos) y los
4 bugs corregidos: Póliza/Servicios Públicos faltantes, abreviatura "PA",
suma de líneas duplicadas y split de arriendo por etiqueta.
"""
from app.services.conciliacion_mandatos import (
    parse_asientos, extract_mandate, suggest_tag, reconciliar,
    parse_mandato_number, parse_asiento_number, expandir_abreviaturas,
)


# ── Parseo numérico por fuente (US vs CO) ────────────────────────────────────

def test_parse_mandato_number_formato_us():
    assert parse_mandato_number("2,011.51") == 2011.51
    assert parse_mandato_number("$ 2,011,510.00") == 2011510
    assert parse_mandato_number("497,333") == 497333
    assert parse_mandato_number("-1,000.50") == -1000.5
    assert parse_mandato_number("") == 0
    assert parse_mandato_number(None) == 0
    assert parse_mandato_number(2011.51) == 2011.51


def test_parse_asiento_number_formato_co():
    assert parse_asiento_number("2.011,51") == 2011.51
    assert parse_asiento_number("129.413") == 129413  # son miles
    assert parse_asiento_number("129") == 129
    assert parse_asiento_number("$ 1.234.567,89") == 1234567.89
    assert parse_asiento_number("-1.000,50") == -1000.5
    assert parse_asiento_number(None) == 0


def test_mismo_valor_distinta_fuente_coincide():
    assert abs(parse_mandato_number("2,011.51") - parse_asiento_number("2.011,51")) < 0.001


# ── STRADA / ESTRADA: emparejamiento por palabra completa ────────────────────

TAG = "MINIGRANJA SOLAR LA RESERVA"


def test_strada_no_suma_estrada():
    details = [
        {"asociado": "STRADA ASOCIADOS S A S", "acc": "28151002", "accDesc": "", "debe": 497333, "haber": 0, "etiqueta": "", "proj": TAG},
        {"asociado": "INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C.", "acc": "28151002", "accDesc": "", "debe": 2655667, "haber": 0, "etiqueta": "", "proj": TAG},
    ]
    res = reconciliar({"mandante": "STRADA ASOCIADOS S.A.S.", "vals": {"mant": 497333}, "total": 497333}, details, TAG)
    assert res["sums"]["mant"] == 497333  # NO 3153000
    assert len(res["lines"]) == 1
    assert res["status"] == "ok"


# ── extract_mandate lee mandante/NIT/total del cuerpo ────────────────────────

def test_extract_mandate_cuerpo_pdf():
    pdf = (
        "CMU12345\n"
        "en calidad de mandatario, y STRADA ASOCIADOS S.A.S., con NIT. 900.123.456-7, "
        "en calidad de mandante, relacionado con el proyecto MINIGRANJA SOLAR LA RESERVA.\n"
        "MANTENIMIENTO $ 497,333.00\n"
        "VALOR A PAGAR $ 497,333.00"
    )
    m = extract_mandate(pdf, "x-CMU12345.pdf")
    assert "STRADA" in m["mandante"]
    assert m["nit"] == "900.123.456-7"
    assert m["vals"]["mant"] == 497333
    assert m["total"] == 497333


def test_parse_asientos_y_suggest_tag():
    rows = [
        ["Asiento contable", "Asociado", "Cuenta", "Debe", "Haber", "Etiqueta", "Cuenta analitica"],
        ["AS1", "STRADA ASOCIADOS S A S", "28151002 Mantenimiento", "497333", "0", "x", TAG],
    ]
    pa = parse_asientos(rows)
    assert len(pa["details"]) == 1 and TAG in pa["tags"]
    assert suggest_tag("La Reserva", pa["tags"], {})["tag"] == TAG


# ── Arriendo La Esmeralda: se suma el débito, no el neto ──────────────────────

def test_arriendo_suma_debitos_no_neto():
    ESM = "[10038] LA ESMERALDA"
    BANC = "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA SA SOCIEDAD FIDUCIARIA"
    deb = 368513.81
    lineas = []
    for ct in ["30980", "30976", "30982", "30978", "30974"]:
        lineas.append({"asociado": BANC, "acc": "28150517", "accDesc": "", "debe": 0, "haber": deb, "etiqueta": ct, "proj": ESM})
        lineas.append({"asociado": BANC, "acc": "28150517", "accDesc": "", "debe": deb, "haber": 0, "etiqueta": ct, "proj": ESM})
    for p, ct in zip(["EDGARDO AROCA", "DULM AROCA", "CARLOS AROCA"], ["30982", "30978", "30974"]):
        lineas.append({"asociado": p, "acc": "28150517", "accDesc": "", "debe": 0, "haber": 184256.91, "etiqueta": ct, "proj": ESM})
    res = reconciliar({"mandante": BANC, "vals": {"arr": 1842569}, "total": 1842569}, lineas, ESM)
    assert round(res["sums"]["arr"]) == 1842569  # NO 0, NO 184257
    assert all(l["asociado"] == BANC for l in res["lines"])
    assert res["status"] == "ok"


# ── BUG 1: Póliza / IVA póliza / Servicios Públicos ──────────────────────────

def test_bug1_poliza_y_servicios_publicos():
    tag = "[10099] PLANTA POLIZA"
    mand = "ACME S A S"
    pdf = (
        "CMU7001\n"
        "en calidad de mandatario, y ACME S.A.S., con NIT. 900.111.222-3, en calidad de "
        "mandante, relacionado con el proyecto PLANTA POLIZA.\n"
        "POLIZA TODO RIESGO Y LUCROCESANTE $ 500,000.00\n"
        "IVA POLIZA $ 95,000.00\n"
        "SERVICIOS PUBLICOS - CONSUMO DE ENERGIA $ 300,000.00\n"
        "VALOR A PAGAR $ 895,000.00"
    )
    m = extract_mandate(pdf, "x-CMU7001.pdf")
    assert m["vals"]["poliza"] == 500000
    assert m["vals"]["iva_poliza"] == 95000  # NO cae en poliza
    assert m["vals"]["serv_pub"] == 300000
    lineas = [
        {"asociado": mand, "acc": "28151004", "accDesc": "", "debe": 500000, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": mand, "acc": "28151007", "accDesc": "", "debe": 95000, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": mand, "acc": "28151008", "accDesc": "", "debe": 300000, "haber": 0, "etiqueta": "", "proj": tag},
    ]
    res = reconciliar(m, lineas, tag)
    assert res["sums"]["poliza"] == 500000
    assert res["sums"]["iva_poliza"] == 95000
    assert res["sums"]["serv_pub"] == 300000
    assert res["status"] == "ok"


# ── BUG 2: abreviatura "PA" (Patrimonio Autónomo) — caso Nestlé ───────────────

def test_bug2_expandir_pa():
    assert "PATRIMONIOS AUTONOMOS" in expandir_abreviaturas("FIDUCIARIA BANCOLOMBIA PA NESTLE 18254")
    # "PARQUE" NO debe expandirse (solo la palabra completa "PA")
    assert "PATRIMONIOS AUTONOMOS" not in expandir_abreviaturas("PARQUE INDUSTRIAL")


def test_bug2_nestle_pa_reconoce_mandante():
    tag = "[18254] NESTLE"
    mand_full = "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA NESTLE"
    aso_abrev = "FIDUCIARIA BANCOLOMBIA PA NESTLE 18254"
    lineas = [
        {"asociado": aso_abrev, "acc": "28151002", "accDesc": "", "debe": 1000000, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": aso_abrev, "acc": "28151003", "accDesc": "", "debe": 190000, "haber": 0, "etiqueta": "", "proj": tag},
    ]
    res = reconciliar({"mandante": mand_full, "vals": {"mant": 1000000, "iva_mant": 190000}, "total": 1190000}, lineas, tag)
    assert len(res["lines"]) == 2  # "PA" reconocido
    assert res["sums"]["mant"] == 1000000 and res["sums"]["iva_mant"] == 190000
    assert res["status"] == "ok"


# ── BUG 3: líneas duplicadas del mismo concepto se SUMAN, no se pisan ─────────

def test_bug3_suma_lineas_duplicadas():
    pdf = (
        "CMU7004\n"
        "en calidad de mandatario, y ACME S.A.S., con NIT. 900.000.000-0, en calidad de "
        "mandante, relacionado con el proyecto PLANTA DUP2.\n"
        "ARRIENDO $ 40,000.00\n"
        "ARRIENDO $ 39,705.00\n"
        "VALOR A PAGAR $ 79,705.00"
    )
    m = extract_mandate(pdf, "x-CMU7004.pdf")
    assert m["vals"]["arr"] == 79705  # NO 39705 (pisado)


# ── BUG 4: split de arriendo por etiqueta del asiento — caso La Reserva ───────

def test_bug4_split_arriendo_por_etiqueta():
    pdf = (
        "CMU1136\n"
        "en calidad de mandatario, y STRADA ASOCIADOS S.A.S., con NIT. 900.123.456-7, en "
        "calidad de mandante, relacionado con el proyecto MINIGRANJA SOLAR LA RESERVA.\n"
        "ARRIENDO CUENTA DE COBRO $ 79,705.00\n"
        "ARRIENDO FACTURA ELECTRONICA $ 79,706.00\n"
        "VALOR A PAGAR $ 159,411.00"
    )
    m = extract_mandate(pdf, "x-CMU1136.pdf")
    assert m["vals"]["arr_cc"] == 79705  # reglas específicas antes de la genérica
    assert m["vals"]["arr_fact"] == 79706
    assert "arr" not in m["vals"]

    mand = "STRADA ASOCIADOS S A S"
    lineas = [
        {"asociado": mand, "acc": "28150517", "accDesc": "", "debe": 79705, "haber": 0, "etiqueta": "ARRIENDO CC 40100", "proj": TAG},
        {"asociado": mand, "acc": "28150517", "accDesc": "", "debe": 79706, "haber": 0, "etiqueta": "ARRIENDO FACT 40101", "proj": TAG},
    ]
    res = reconciliar(m, lineas, TAG)
    assert res["sums"]["arr_cc"] == 79705  # etiqueta CC
    assert res["sums"]["arr_fact"] == 79706  # etiqueta FACT
    assert "arr" not in res["sums"]
    assert res["status"] == "ok"


# ── BUG 5: Administración / IVA administración ────────────────────────────────

def test_bug5_administracion():
    tag = "[10100] PLANTA ADMIN"
    mand = "ACME S A S"
    pdf = (
        "CMU7002\n"
        "en calidad de mandatario, y ACME S.A.S., con NIT. 900.111.222-3, en calidad de "
        "mandante, relacionado con el proyecto PLANTA ADMIN.\n"
        "ADMINISTRACION DE PROYECTOS $ 200,000.00\n"
        "IVA ADMINISTRACION $ 38,000.00\n"
        "VALOR A PAGAR $ 238,000.00"
    )
    m = extract_mandate(pdf, "x-CMU7002.pdf")
    assert m["vals"]["admin"] == 200000
    assert m["vals"]["iva_admin"] == 38000  # NO cae en admin
    lineas = [
        {"asociado": mand, "acc": "28151020", "accDesc": "", "debe": 200000, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": mand, "acc": "28151021", "accDesc": "", "debe": 38000, "haber": 0, "etiqueta": "", "proj": tag},
    ]
    res = reconciliar(m, lineas, tag)
    assert res["sums"]["admin"] == 200000
    assert res["sums"]["iva_admin"] == 38000
    assert res["status"] == "ok"


# ── BUG 6: asociado abreviado en el asiento (caso real Sol Sierra, CMU1107) ──

def test_bug6_asociado_abreviado_subconjunto():
    tag = "[10051] COLCEST53P1 LA PAZ LEYENDA"
    mand = "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"
    lineas = [
        {"asociado": "PA 17844 SOL DE LA SIERRA", "acc": "28151009", "accDesc": "", "debe": 64706.3, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": "PA 17844 SOL DE LA SIERRA", "acc": "28151010", "accDesc": "", "debe": 12294.2, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": "PA 17844 SOL DE LA SIERRA", "acc": "28151020", "accDesc": "", "debe": 2681883.45, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": "PA 17844 SOL DE LA SIERRA", "acc": "28151021", "accDesc": "", "debe": 509557.86, "haber": 0, "etiqueta": "", "proj": tag},
        # Ruido: otro tercero del MISMO proyecto que NO debe sumarse.
        {"asociado": "SOLENIUM SAS", "acc": "28151020", "accDesc": "", "debe": 999999, "haber": 0, "etiqueta": "", "proj": tag},
        # Otro patrimonio Bancolombia con fondo DISTINTO (Nestlé 18254): NO debe cruzar.
        {"asociado": "FIDUCIARIA BANCOLOMBIA PA NESTLE 18254", "acc": "28151020", "accDesc": "", "debe": 888888, "haber": 0, "etiqueta": "", "proj": tag},
    ]
    res = reconciliar({"mandante": mand, "vals": {"int": 64706.3, "iva_int": 12294.2, "admin": 2681883.45, "iva_admin": 509557.86}, "total": 3268441.81}, lineas, tag)
    assert len(res["lines"]) == 4  # solo las 4 de "PA 17844 SOL DE LA SIERRA"
    assert round(res["sums"]["admin"]) == 2681883  # sin sumar 999999/888888
    assert res["status"] == "ok"  # antes: todo faltante, suma 0


def test_bug6_fondos_distintos_no_cruzan():
    tag = "[10051] COLCEST53P1 LA PAZ LEYENDA"
    lineas = [
        {"asociado": "PA 17844 SOL DE LA SIERRA", "acc": "28151020", "accDesc": "", "debe": 100, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": "FIDUCIARIA BANCOLOMBIA PA NESTLE 18254", "acc": "28151020", "accDesc": "", "debe": 200, "haber": 0, "etiqueta": "", "proj": tag},
        {"asociado": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.", "acc": "28151020", "accDesc": "", "debe": 300, "haber": 0, "etiqueta": "", "proj": tag},
    ]
    # Sol Sierra (17844) solo suma su línea; Nestlé (18254) y Skandia quedan fuera.
    res = reconciliar({"mandante": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA",
                       "vals": {"admin": 100}, "total": 100}, lineas, tag)
    assert res["sums"]["admin"] == 100
    assert len(res["lines"]) == 1


def test_bug4_etiqueta_sin_cc_fact_queda_generico():
    mand = "STRADA ASOCIADOS S A S"
    lineas = [{"asociado": mand, "acc": "28150517", "accDesc": "", "debe": 100, "haber": 0, "etiqueta": "ARRIENDO ABRIL", "proj": TAG}]
    res = reconciliar({"mandante": mand, "vals": {"arr": 100}, "total": 100}, lineas, TAG)
    assert res["sums"]["arr"] == 100  # sin CC/FACT sigue en 'arr' genérico
