"""Comparar lo que daría la API contra lo que dio el Excel, sin guardar nada.

Es el paso previo a confiar en el cambio: deja ver, concepto por concepto, en qué
se diferencian, para poder distinguir las diferencias esperadas -- la
administración de los 9 GD, FAZNI y confiabilidad-- de un fallo de traducción.
"""
from app.api.v1.panel_contable import comparar_lineas


def _l(grupo, concepto, valor):
    return {"grupo": grupo, "concepto": concepto, "valor": valor}


def test_no_reporta_lo_que_coincide():
    """Una lista vacía significa que la API produce lo mismo que el Excel."""
    assert comparar_lineas(
        excel=[_l("ingresos", "Terpel", 100.0)],
        api=[_l("ingresos", "Terpel", 100.0)],
    ) == []


def test_marca_las_diferencias_de_valor():
    dif = comparar_lineas(excel=[_l("ingresos", "Terpel", 100.0)],
                          api=[_l("ingresos", "Terpel", 150.0)])
    assert dif[0]["excel"] == 100.0 and dif[0]["api"] == 150.0
    assert dif[0]["diferencia"] == 50.0


def test_marca_lo_que_solo_esta_en_el_excel():
    """El caso de los 9 GD: el Excel les cobra administración y la API no."""
    dif = comparar_lineas(
        excel=[_l("facturas", "Administración", -5_836_668.0)], api=[])
    assert dif[0]["solo_en"] == "excel"
    assert dif[0]["api"] is None


def test_marca_lo_que_solo_esta_en_la_api():
    """El caso de FAZNI: la API lo trae y el Excel no."""
    dif = comparar_lineas(
        excel=[], api=[_l("comercializacion", "FAZNI", -504_489.0)])
    assert dif[0]["solo_en"] == "api"
    assert dif[0]["excel"] is None


def test_tolera_diferencias_de_redondeo():
    """Un peso de diferencia es redondeo, no discrepancia."""
    assert comparar_lineas(excel=[_l("ingresos", "T", 100.00)],
                           api=[_l("ingresos", "T", 100.004)]) == []


def test_dos_pesos_si_es_diferencia():
    assert comparar_lineas(excel=[_l("ingresos", "T", 100.0)],
                           api=[_l("ingresos", "T", 102.0)]) != []


def test_suma_las_lineas_del_mismo_concepto():
    """Las del panel vienen divididas por inversionista: hay que reagruparlas
    al 100% para poder compararlas con lo que produce la API."""
    assert comparar_lineas(
        excel=[_l("ingresos", "Terpel", 60.0), _l("ingresos", "Terpel", 40.0)],
        api=[_l("ingresos", "Terpel", 100.0)],
    ) == []


def test_el_mismo_concepto_en_otro_grupo_no_se_confunde():
    """CGM vive en 'facturas' y Cobro OPEX: CGM en 'costos': son distintos."""
    dif = comparar_lineas(excel=[_l("facturas", "CGM", 100.0)],
                          api=[_l("costos", "CGM", 100.0)])
    assert len(dif) == 2


def test_ordena_por_grupo_y_concepto():
    """Para que dos corridas se puedan comparar entre sí."""
    dif = comparar_lineas(
        excel=[_l("ingresos", "B", 1.0), _l("costos", "A", 1.0)], api=[])
    assert [(d["grupo"], d["concepto"]) for d in dif] == [("costos", "A"), ("ingresos", "B")]


def test_un_valor_nulo_cuenta_como_cero():
    assert comparar_lineas(excel=[_l("ingresos", "T", None)],
                           api=[_l("ingresos", "T", 0.0)]) == []


def test_una_linea_en_cero_de_un_solo_lado_no_es_diferencia():
    """36 proyectos arrastran conceptos vacíos del comercializador; reportarlos
    tapaba las diferencias que sí mueven plata."""
    assert comparar_lineas(
        excel=[], api=[_l("comercializacion", "IVA Comercializador", 0.0)]) == []


def test_pero_un_valor_real_de_un_solo_lado_si_lo_es():
    assert comparar_lineas(
        excel=[], api=[_l("comercializacion", "FAZNI (Gen)", -504_489.0)]) != []
