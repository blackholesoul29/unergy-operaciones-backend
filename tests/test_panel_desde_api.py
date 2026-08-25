"""Traducción de income_statement_data al formato que consume el Panel.

El Panel se arma con `_guardar_panel(..., parsed, ...)`, donde `parsed` es el dict
que hasta ahora producía `parsear_er()` leyendo el Excel. Estas pruebas fijan esa
forma: si cambia, `_guardar_panel` deja de entender lo que recibe.
"""
import pytest

from app.services.panel_desde_api import TOPICOS_QUE_COMPRAN, construir_parsed


def _proyecto_api(**extra):
    base = {
        "project": "vallenata",
        "project_name": "MGS 0007 La Paz Vallenata",
        "generacion_kwh": 213_000.0,
        "importacion_kwh": 715.71,
        "ingreso_bruto": 77_464_585.0,
        "venta": 77_464_585.0,
        "compra": 0.0,
        "tiene_bolsa": False,
        "comercializadores": ["Terpel"],
        "ingresos_detalle": [
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 110_000.0, "valor": 40_189_569.0},
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 103_000.0, "valor": 37_275_016.0},
        ],
        "comercializacion": [
            {"concepto": "Energía en bolsa", "name": "energia_bolsa_generador",
             "valor": 834_708.0, "iva": False},
        ],
        "warnings": [],
    }
    base.update(extra)
    return base


# ── Ingresos ─────────────────────────────────────────────────────────────────

def test_suma_los_ingresos_de_todos_los_contratos():
    """Una planta con dos contratos factura por los dos.

    Vallenata trae 40.189.569 + 37.275.016 y cuadra al peso con el Excel.
    """
    parsed = construir_parsed(_proyecto_api())
    assert parsed["total_ingresos"] == 77_464_585.0
    assert len(parsed["ingresos_detalle"]) == 2


def test_conserva_una_linea_por_contrato():
    """Colapsarlas perdería de dónde viene cada peso."""
    parsed = construir_parsed(_proyecto_api())
    assert [d["valor"] for d in parsed["ingresos_detalle"]] == [40_189_569.0, 37_275_016.0]


def test_la_venta_en_bolsa_tambien_suma():
    parsed = construir_parsed(_proyecto_api(ingresos_detalle=[
        {"concepto": "Neu Venta", "data_type": "dispatch", "valor": 100.0},
        {"concepto": "Neu Venta bolsa", "data_type": "dispatch_fazni", "valor": 50.0},
    ]))
    assert parsed["total_ingresos"] == 150.0


def test_el_ingreso_bruto_es_el_total_de_ingresos():
    """El Panel usa los dos y deben coincidir."""
    parsed = construir_parsed(_proyecto_api())
    assert parsed["ingreso_bruto"] == parsed["total_ingresos"]


def test_toma_los_kwh_de_generacion():
    assert construir_parsed(_proyecto_api())["kwh"] == 213_000.0


def test_sin_generacion_los_kwh_van_en_none():
    """Un cero haría que Repre y CGM se calcularan en cero; None los deja sin tocar."""
    assert construir_parsed(_proyecto_api(generacion_kwh=0))["kwh"] is None


def test_toma_el_primer_comercializador():
    assert construir_parsed(_proyecto_api())["comercializador"] == "Terpel"


def test_sin_comercializador_no_revienta():
    assert construir_parsed(_proyecto_api(comercializadores=[]))["comercializador"] is None


def test_el_tipo_siempre_es_normal():
    """NEU y Nitro no pasan por aquí: siguen cargando el Excel."""
    assert construir_parsed(_proyecto_api())["tipo"] == "normal"


def test_no_trae_snapshot():
    """El snapshot es de celdas del Excel; desde la API no aplica."""
    assert construir_parsed(_proyecto_api())["snapshot"] == {}


# ── Compras ──────────────────────────────────────────────────────────────────

COMPRA_FANTASMA = {"concepto": "Terpel Compra", "data_type": "purchase",
                   "energia_kwh": 210_740.66, "valor": -148_282_984.0}


def test_una_compra_inesperada_no_baja_el_ingreso():
    """La Paz Verso traía una compra por los mismos kWh que vendió, con el ingreso
    bruto en -71M. Restarla habría bajado la administración casi un 8%."""
    parsed = construir_parsed(_proyecto_api(
        project="verso", ingresos_detalle=[
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 210_740.66, "valor": 76_949_845.0},
            COMPRA_FANTASMA,
        ]))
    assert parsed["total_ingresos"] == 76_949_845.0
    assert len(parsed["ingresos_detalle"]) == 1


def test_una_compra_inesperada_queda_avisada():
    """Excluirla en silencio esconde un error de datos aguas arriba."""
    parsed = construir_parsed(_proyecto_api(
        project="verso", ingresos_detalle=[COMPRA_FANTASMA]))
    assert any("compra" in w.lower() for w in parsed["warnings"])


def test_las_compras_legitimas_si_restan():
    """Baraya sí compra: ahí la compra es parte del negocio."""
    parsed = construir_parsed(_proyecto_api(
        project="baraya", ingresos_detalle=[
            {"concepto": "Neu Venta", "data_type": "dispatch",
             "energia_kwh": 100.0, "valor": 69_436_902.0},
            {"concepto": "Neu Compra", "data_type": "purchase",
             "energia_kwh": 50.0, "valor": -12_458_625.0},
        ]))
    assert parsed["total_ingresos"] == 56_978_277.0
    assert len(parsed["ingresos_detalle"]) == 2
    assert parsed["warnings"] == []


@pytest.mark.parametrize("topico", sorted(TOPICOS_QUE_COMPRAN))
def test_ningun_topico_de_la_lista_avisa(topico):
    parsed = construir_parsed(_proyecto_api(
        project=topico, ingresos_detalle=[COMPRA_FANTASMA]))
    assert parsed["warnings"] == []


@pytest.mark.parametrize("topico", ["delta_2", "naos2", "naos3", "polaris_2"])
def test_no_confundir_delta_1_con_delta_2(topico):
    """delta_2, naos2, naos3 y polaris_2 NO están en la lista de los que compran."""
    parsed = construir_parsed(_proyecto_api(
        project=topico, ingresos_detalle=[COMPRA_FANTASMA]))
    assert parsed["warnings"], f"{topico} debería avisar"


def test_el_aviso_dice_cuanto_se_excluyo():
    """Sin la cifra, el aviso no deja dimensionar el problema."""
    parsed = construir_parsed(_proyecto_api(
        project="verso", ingresos_detalle=[COMPRA_FANTASMA]))
    assert "148,282,984" in parsed["warnings"][0]


# ── Comercialización ─────────────────────────────────────────────────────────

COMERCIALIZACION_API = [
    {"concepto": "Energía en bolsa", "name": "energia_bolsa_generador",
     "valor": 616_662.0, "iva": False},
    {"concepto": "Servicios de despacho", "name": "servicios_despacho_generador",
     "valor": 500_558.0, "iva": False},
    {"concepto": "FAZNI", "name": "fazni_generador", "valor": 59_000.0, "iva": False},
    {"concepto": "Cargo por confiabilidad", "name": "cargo_confiabilidad_generador",
     "valor": 40_000.0, "iva": False},
]


def test_la_comercializacion_entra_en_negativo():
    """Son costos: el Panel los guarda con signo negativo."""
    parsed = construir_parsed(_proyecto_api(comercializacion=COMERCIALIZACION_API))
    valores = {l["concepto"]: l["valor"] for l in parsed["comercializacion"]}
    assert valores["Energía en bolsa"] == -616_662.0


def test_trae_fazni_y_cargo_por_confiabilidad():
    """El Excel no las tiene; son 10,5M de costo real en julio de 2026."""
    parsed = construir_parsed(_proyecto_api(comercializacion=COMERCIALIZACION_API))
    conceptos = {l["concepto"] for l in parsed["comercializacion"]}
    assert "FAZNI" in conceptos
    assert "Cargo por confiabilidad" in conceptos


def test_los_warnings_de_la_api_se_conservan():
    """Si la API avisa que le faltó una fila, sus cifras están incompletas y eso
    tiene que llegar a la pantalla, no quedarse en el JSON."""
    parsed = construir_parsed(_proyecto_api(
        warnings=["Falta la fila 'fazni_generador'."]))
    assert any("fazni" in w.lower() for w in parsed["warnings"])


def test_sin_comercializacion_no_revienta():
    assert construir_parsed(_proyecto_api(comercializacion=[]))["comercializacion"] == []


def test_los_costos_y_facturas_los_pone_el_panel():
    """OPEX, Repre, CGM y Administración salen de nuestros módulos, no de la API."""
    parsed = construir_parsed(_proyecto_api())
    assert parsed["costos"] == []
    assert parsed["facturas"] == []
