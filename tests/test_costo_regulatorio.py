"""Costo regulatorio del mes desde la hoja 'Facturas XM' del Cruce de facturas.
Cálculo puro: sin BD, sin red, sin reloj."""
from app.services.costo_regulatorio import (
    _norm,
    costo_regulatorio_de_facturas,
)


def _factura(asic, tipo, lineas):
    return {"asic": asic, "tipo": tipo, "lineas": lineas}


def test_norm_quita_acentos_y_normaliza():
    assert _norm("  Energía en Bolsa ") == "energia en bolsa"
    assert _norm("COMERCIALIZADOR") == "comercializador"


def test_excluye_comercializador_completo():
    facturas = [
        _factura("ASIC1", "COMERCIALIZADOR", [("Servicios de administracion sic", 800000.0),
                                              ("Valor total", 800000.0)]),
        _factura("ASIC2", "GENERADOR", [("Fazni", 999626.0), ("Valor total", 999626.0)]),
    ]
    assert costo_regulatorio_de_facturas(facturas) == 999626.0


def test_excluye_energia_en_bolsa_y_subtotales():
    facturas = [_factura("ASIC3", "GENERADOR", [
        ("Arranque y parada", 9658866.0),
        ("Cargo por confiabilidad", 19933106.0),
        ("Energia en bolsa", 110102600.0),   # excluido: es "compras"
        ("Valor total", 139694572.0),         # subtotal: no sumar
    ])]
    assert costo_regulatorio_de_facturas(facturas) == 29591972.0


def test_iva_generador_si_entra_y_total_servicios_no():
    facturas = [_factura("ASIC4", "GENERADOR", [
        ("+ i.v.a. (19%)", 1742857.0),
        ("Servicios de administracion sic", 9172932.0),
        ("Servicios despacho y coordinacion cnd", 25684211.0),
        ("Total servicios de administracion sic", 10915789.0),  # subtotal: no sumar
        ("Valor total", 36600000.0),                            # subtotal: no sumar
    ])]
    assert costo_regulatorio_de_facturas(facturas) == 36600000.0


def test_total_julio_2026_reproduce_valor_referencia():
    facturas = [
        _factura("ASIC125059", "COMERCIALIZADOR", [
            ("+ i.v.a. (19%)", 151994.0), ("Servicios de administracion sic", 799970.0),
            ("Servicios despacho y coordinacion cnd", 426693.0),
            ("Total servicios de administracion sic", 951964.0), ("Valor total", 1378657.0)]),
        _factura("ASIC125064", "GENERADOR", [("Fazni", 999626.0), ("Valor total", 999626.0)]),
        _factura("ASIC125263", "GENERADOR", [
            ("Arranque y parada", 9658866.0), ("Cargo por confiabilidad", 19933106.0),
            ("Energia en bolsa", 110102600.0), ("Valor total", 139694572.0)]),
        _factura("ASIC125542", "GENERADOR", [
            ("+ i.v.a. (19%)", 1742857.0), ("Servicios de administracion sic", 9172932.0),
            ("Servicios despacho y coordinacion cnd", 25684211.0),
            ("Total servicios de administracion sic", 10915789.0), ("Valor total", 36600000.0)]),
    ]
    assert costo_regulatorio_de_facturas(facturas) == 67191598.0


import openpyxl
from app.services.costo_regulatorio import extraer_facturas_xm


def _hoja_demo():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturas XM"
    filas = [
        ["Factura ASIC1 - COMERCIALIZADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Servicios de administracion sic", 1, 0, 0, 800000.0],
        ["Valor total", 1, 0, 0, 800000.0],
        [None, None, None, None, None],
        ["Factura ASIC2 - GENERADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Fazni", 1, 0, 0, 999626.0],
        ["Valor total", 1, 0, 0, 999626.0],
    ]
    for r in filas:
        ws.append(r)
    return ws


def test_extraer_facturas_separa_encabezado_tipo_y_lineas():
    facturas = extraer_facturas_xm(_hoja_demo())
    assert [f["asic"] for f in facturas] == ["ASIC1", "ASIC2"]
    assert [f["tipo"] for f in facturas] == ["COMERCIALIZADOR", "GENERADOR"]
    assert ("Fazni", 999626.0) in facturas[1]["lineas"]
    # la fila 'campo' (header) NO es una línea de concepto
    assert all(l[0] != "campo" for f in facturas for l in f["lineas"])


def test_extraer_y_calcular_da_solo_generador():
    from app.services.costo_regulatorio import costo_regulatorio_de_facturas
    assert costo_regulatorio_de_facturas(extraer_facturas_xm(_hoja_demo())) == 999626.0
