"""El ER que generamos nosotros, en Excel.

Conserva la estructura del que usan hoy (ejemplo: QUANTUM ENERGY · GRANJA SOLAR
SAN AGUSTIN 7 2026): tabla diaria arriba con la columna de Importación, los tres
bloques de totales, y el detalle del partícipe a la derecha.

Con los valores ya calculados -- no fórmulas sin evaluar, que es el defecto del
archivo de la API y la razón por la que hoy hace falta LibreOffice.
"""
import io
import types

from openpyxl import load_workbook

from app.services.er_export import generar_er_xlsx


def _linea(grupo, concepto, valor, inv="QUANTUM ENERGY S.A.S", pct=100.0):
    return types.SimpleNamespace(grupo=grupo, concepto=concepto, valor_cop=valor,
                                 inversionista_nombre=inv, porcentaje=pct, orden=0)


PANEL = types.SimpleNamespace(
    periodo="2026-07",
    comercializador="UNERGY ENERGIA DIGITAL S.A.S ESP",
    lineas=[
        _linea("ingresos", "Venta en bolsa", 118_673_860.5),
        _linea("comercializacion", "Energía en Bolsa (Gen)", -603_083.64),
        _linea("comercializacion", "Arranque y parada", -171_129.13),
        _linea("costos", "Cobro OPEX: Representación", -1_011_610.02),
        _linea("facturas", "CGM", -1_011_610.02),
    ],
)

DIARIO = [
    {"fecha": "2026-07-01", "generacion_kwh": 5629.63, "importacion_kwh": 22.52,
     "venta_kwh": 5629.63, "venta_cop": 4_491_783.26},
    {"fecha": "2026-07-02", "generacion_kwh": 3597.46, "importacion_kwh": 23.62,
     "venta_kwh": 3597.46, "venta_cop": 2_839_856.69},
]


def _celdas(contenido):
    wb = load_workbook(io.BytesIO(contenido), data_only=True)
    return [c.value for fila in wb.active.iter_rows() for c in fila]


# ── Tabla diaria ─────────────────────────────────────────────────────────────

def test_la_tabla_diaria_trae_la_importacion():
    """El consumo es una columna del ER, no un dato aparte."""
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "Importación (kWh)" in valores
    assert 22.52 in valores


def test_la_tabla_diaria_trae_una_fila_por_dia():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "2026-07-01" in valores and "2026-07-02" in valores


def test_la_fila_total_suma_las_columnas():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "TOTAL" in valores
    assert round(5629.63 + 3597.46, 2) in valores      # generación
    assert round(22.52 + 23.62, 2) in valores          # importación


def test_el_encabezado_de_venta_nombra_al_comercializador():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert any(isinstance(v, str) and "UNERGY ENERGIA DIGITAL" in v for v in valores)


def test_sin_datos_diarios_no_revienta():
    """Un período sin FTP descargado igual tiene que poder verse."""
    assert _celdas(generar_er_xlsx(PANEL, "X", diario=[]))


# ── Bloques de totales ───────────────────────────────────────────────────────

def test_trae_los_tres_bloques():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    for titulo in ("Ingresos y costos XM", "Total Comercialización",
                   "Total Ingresos", "Total Costos Operativos fijos",
                   "Total de costos operativos + Comercialización"):
        assert titulo in valores, titulo


def test_los_valores_van_calculados_no_como_formula():
    """Si fueran fórmulas haría falta LibreOffice para leerlos, que es justo lo
    que este cambio elimina."""
    assert 118_673_860.5 in _celdas(generar_er_xlsx(PANEL, "X", diario=DIARIO))


def test_las_facturas_se_leen_dentro_de_costos_operativos():
    """En el ER de hoy los cobros de Unergy van en ese bloque."""
    wb = load_workbook(io.BytesIO(generar_er_xlsx(PANEL, "X", diario=DIARIO)), data_only=True)
    filas = [[c.value for c in f] for f in wb.active.iter_rows()]
    conceptos = [f[2] for f in filas if len(f) > 2]
    assert "CGM" in conceptos


# ── Bloque del partícipe ─────────────────────────────────────────────────────

def test_trae_el_valor_a_pagar():
    valores = _celdas(generar_er_xlsx(PANEL, "X", diario=DIARIO))
    assert "Valor a pagar" in valores
    assert "Porcentaje participación" in valores
    assert "Factura UNERGY" in valores


def test_calcula_las_tarifas_bruta_y_neta():
    valores = _celdas(generar_er_xlsx(PANEL, "X", diario=DIARIO))
    assert "Tarifa bruta" in valores and "Tarifa neta" in valores


def test_sin_energia_no_calcula_tarifas():
    """Dividir por cero reventaría; sin energía esas filas no aplican."""
    valores = _celdas(generar_er_xlsx(PANEL, "X", diario=[]))
    assert "Tarifa bruta" not in valores


# ── Filtro por inversionista ─────────────────────────────────────────────────

def test_filtrar_por_inversionista_deja_solo_lo_suyo():
    panel = types.SimpleNamespace(periodo="2026-07", comercializador="X", lineas=[
        _linea("ingresos", "Venta", 100.0, inv="ACME", pct=60.0),
        _linea("ingresos", "Venta", 40.0, inv="OTRA", pct=40.0),
    ])
    valores = _celdas(generar_er_xlsx(panel, "X", diario=[], inversionista="ACME"))
    assert 100.0 in valores and 40.0 not in valores


def test_el_encabezado_nombra_al_inversionista_filtrado():
    panel = types.SimpleNamespace(periodo="2026-07", comercializador="X", lineas=[
        _linea("ingresos", "Venta", 100.0, inv="ACME", pct=60.0)])
    assert "ACME" in _celdas(generar_er_xlsx(panel, "X", diario=[], inversionista="ACME"))


def test_sin_inversionista_trae_el_proyecto_completo():
    panel = types.SimpleNamespace(periodo="2026-07", comercializador="X", lineas=[
        _linea("ingresos", "Venta", 100.0, inv="ACME", pct=60.0),
        _linea("ingresos", "Venta", 40.0, inv="OTRA", pct=40.0),
    ])
    valores = _celdas(generar_er_xlsx(panel, "X", diario=[]))
    assert 140.0 in valores
    assert "Proyecto (100%)" in valores
