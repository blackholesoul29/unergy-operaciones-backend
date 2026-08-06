"""Tests del motor puro de conciliación Mandato (PDF) vs. Asiento (Excel Odoo).

Mirror en backend de src/utils/conciliacionMandatos.test.mjs del frontend.
Cubre el criterio STRADA/ESTRADA, el neteo de arriendo (suma de débitos) y los
4 bugs corregidos: Póliza/Servicios Públicos faltantes, abreviatura "PA",
suma de líneas duplicadas y split de arriendo por etiqueta.
"""
from app.services.conciliacion_mandatos import (
    parse_asientos, extract_mandate, suggest_tag, reconciliar,
    parse_mandato_number, parse_asiento_number, normalizar_cifra, expandir_abreviaturas,
)


# ── normalizar_cifra: función única que detecta miles/decimal en ambos formatos ──

def test_normalizar_cifra_formato_us():
    assert normalizar_cifra("1,234,567") == 1234567
    assert normalizar_cifra("2,011.51") == 2011.51
    assert normalizar_cifra("$ 2,011,510.00") == 2011510
    assert normalizar_cifra("497,333") == 497333          # una coma, 3 dígitos → miles
    assert normalizar_cifra("0.50") == 0.5
    assert normalizar_cifra("2,681,883.45") == 2681883.45  # caso real Sol Sierra


def test_normalizar_cifra_formato_co():
    assert normalizar_cifra("1.234.567") == 1234567
    assert normalizar_cifra("2.011,51") == 2011.51
    assert normalizar_cifra("129.413") == 129413           # un punto, 3 dígitos → miles
    assert normalizar_cifra("$ 1.234.567,89") == 1234567.89
    assert normalizar_cifra("0,50") == 0.5


def test_normalizar_cifra_bordes():
    assert normalizar_cifra("129") == 129
    assert normalizar_cifra("-1,000.50") == -1000.5
    assert normalizar_cifra("-1.000,50") == -1000.5
    assert normalizar_cifra("(1.234)") == -1234            # paréntesis contable = negativo
    assert normalizar_cifra(2011.51) == 2011.51            # número nativo pasa directo
    assert normalizar_cifra("") == 0 and normalizar_cifra(None) == 0
    # Mismo valor, distinta fuente → coinciden (no diferencia de miles)
    assert abs(normalizar_cifra("2,011.51") - normalizar_cifra("2.011,51")) < 0.001
    # Regresión "Auditoría PDFs": US con comas NO debe leerse como 2.011
    assert normalizar_cifra("2,011,510.00") != 2.011


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


# ── Mantenimiento pagado al contratista vía cuenta de Administración ────────
# (caso real Nestlé/Solenium: el mandato dice "no aparece" pero el monto SÍ
# está contabilizado, solo que en 28151020/21 con el contratista de Asociado
# en vez de 28151002/03 con la fiduciaria).

def test_mantenimiento_registrado_en_cuenta_admin_con_otro_asociado():
    tag = "[10002] PROYECTO-NESTLE"
    fiduciaria = "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"
    lineas = [
        {"asociado": "SOLENIUM SAS", "acc": "28151020", "accDesc": "COSTOS PARA TERCEROS - ADMINISTRACION DE PROYECTOS",
         "debe": 6831500, "haber": 0, "etiqueta": "Mantenimiento Preventivo - Nestle", "proj": tag},
        {"asociado": "SOLENIUM SAS", "acc": "28151021", "accDesc": "IVA ADMINISTRACION DE PROYECTOS - COSTOS PARA TERCEROS",
         "debe": 1297985, "haber": 0, "etiqueta": "Mantenimiento Preventivo - Nestle", "proj": tag},
    ]
    m = {"mandante": fiduciaria, "vals": {"mant": 6831500, "iva_mant": 1297985}, "total": 8129485}
    res = reconciliar(m, lineas, tag)
    codes = {f["code"] for f in res["flags"]}
    assert "FALTANTE" not in codes  # no debe reportarse como ausente...
    assert "OTRA_CUENTA" in codes   # ...sino como aviso de cuenta/asociado distinto
    otra = [f for f in res["flags"] if f["code"] == "OTRA_CUENTA"]
    assert any("28151020" in f["txt"] and "SOLENIUM SAS" in f["txt"] for f in otra)
    assert res["status"] == "warn"  # no "bad": el dinero sí está, solo mal clasificado


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


def test_bug4b_arriendo_cc_cuenta_nueva_no_responsable_iva():
    """La cuenta de la CC cambió a 28151025 (arrendador no responsable de IVA);
    antes no estaba en ACC2CONCEPT y la línea se descartaba en silencio, por lo
    que el mandato reportaba "FALTANTE" aunque el asiento sí traía el arriendo.
    """
    pdf = (
        "CMU1136\n"
        "en calidad de mandatario, y STRADA ASOCIADOS S.A.S., con NIT. 900.123.456-7, en "
        "calidad de mandante, relacionado con el proyecto MINIGRANJA SOLAR LA RESERVA.\n"
        "ARRIENDO CUENTA DE COBRO $ 79,705.00\n"
        "ARRIENDO FACTURA ELECTRONICA $ 79,706.00\n"
        "VALOR A PAGAR $ 159,411.00"
    )
    m = extract_mandate(pdf, "x-CMU1136.pdf")

    mand = "STRADA ASOCIADOS S A S"
    lineas = [
        {"asociado": mand, "acc": "28151025", "accDesc": "", "debe": 79705, "haber": 0, "etiqueta": "ARRIENDO CC JULIO LA RESERVA", "proj": TAG},
        {"asociado": mand, "acc": "28150517", "accDesc": "", "debe": 79706, "haber": 0, "etiqueta": "ARRIENDO FACT JULIO LA RESERVA", "proj": TAG},
    ]
    res = reconciliar(m, lineas, TAG)
    assert res["sums"]["arr_cc"] == 79705
    assert res["sums"]["arr_fact"] == 79706
    assert res["status"] == "ok"


def test_bug4c_arriendo_redaccion_responsable_no_responsable_iva():
    """Caso real CMU1284 (jul-2026): el mandato dejó de decir "Cuenta de Cobro"/
    "Factura Electrónica" y ahora dice "Arriendo No Responsable de IVA" / "Arriendo
    Responsable de IVA". Antes del fix, el "continue" que evita que "IVA
    MANTENIMIENTO" caiga en 'mant' también disparaba aquí (la frase nueva contiene
    la palabra IVA) y AMBOS montos de arriendo se descartaban en silencio — no
    aparecían ni como OK, ni como FALTANTE, ni como ninguna alerta.
    """
    pdf = (
        "CMU1284\n"
        "en calidad de mandatario, y SOLENIUM S.A.S., con NIT. 900.999.888-1, en "
        "calidad de mandante, relacionado con el proyecto Minigranja Solar Sabana de Torres.\n"
        "Arriendo No Responsable de IVA $ 673,757.00\n"
        "Arriendo Responsable de IVA $ 673,757.00\n"
        "Iva Arriendo $ 128,014.00\n"
        "Servicio de Internet $ 188,236.00\n"
        "Iva Internet $ 35,765.00\n"
        "VALOR A PAGAR $ 1,699,529.00"
    )
    m = extract_mandate(pdf, "x-CMU1284.pdf")
    assert m["vals"]["arr_cc"] == 673757
    assert m["vals"]["arr_fact"] == 673757
    assert m["vals"]["iva_arr"] == 128014
    assert "arr" not in m["vals"]

    mand = "SOLENIUM S A S"
    lineas = [
        {"asociado": mand, "acc": "28151025", "accDesc": "", "debe": 673757, "haber": 0, "etiqueta": "ARRIENDO JULIO", "proj": TAG},
        {"asociado": mand, "acc": "28150517", "accDesc": "", "debe": 673757, "haber": 0, "etiqueta": "ARRIENDO FACT JULIO", "proj": TAG},
        {"asociado": mand, "acc": "28150518", "accDesc": "", "debe": 128014, "haber": 0, "etiqueta": "ARRIENDO FACT JULIO", "proj": TAG},
        {"asociado": mand, "acc": "28151009", "accDesc": "", "debe": 188236, "haber": 0, "etiqueta": "INTERNET JULIO", "proj": TAG},
        {"asociado": mand, "acc": "28151010", "accDesc": "", "debe": 35765, "haber": 0, "etiqueta": "INTERNET JULIO", "proj": TAG},
    ]
    res = reconciliar(m, lineas, TAG)
    assert res["sums"]["arr_cc"] == 673757
    assert res["sums"]["arr_fact"] == 673757
    assert res["status"] == "ok"


def test_bug4d_arriendo_generico_no_responsable_iva_no_se_divide():
    """Caso real CMU1264/1265/1266: el mandato solo lista "Arriendo" genérico
    (un único arrendador, que no es responsable de IVA, sin línea de IVA
    arriendo) y contablemente ese único arrendador cae en la cuenta 28151025.
    Reclasificar esa cuenta a arr_cc SIEMPRE (como hacía el fix anterior) rompía
    este caso: el mandato decía "arr" pero el asiento sumaba "arr_cc" — dos
    claves distintas que nunca coincidían (FALTANTE + SOBRANTE simultáneos).
    Solo debe dividirse cuando el mandato explícitamente separa (bug4b/4c).
    """
    pdf = (
        "CMU1264\n"
        "en calidad de mandatario, y SUNO ACTIVOS SOSTENIBLES S.A.S., con NIT. "
        "900.777.666-2, en calidad de mandante, relacionado con el proyecto "
        "MINIGRANJA EL SON.\n"
        "ARRIENDO $ 874,490.00\n"
        "VALOR A PAGAR $ 874,490.00"
    )
    m = extract_mandate(pdf, "x-CMU1264.pdf")
    assert m["vals"]["arr"] == 874490
    assert "arr_cc" not in m["vals"]
    assert "arr_fact" not in m["vals"]

    mand = "SUNO ACTIVOS SOSTENIBLES S A S"
    lineas = [
        {"asociado": mand, "acc": "28151025", "accDesc": "", "debe": 874490, "haber": 0, "etiqueta": "ARRIENDO JULIO", "proj": TAG},
    ]
    res = reconciliar(m, lineas, TAG)
    assert res["sums"]["arr"] == 874490
    assert "arr_cc" not in res["sums"]
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
