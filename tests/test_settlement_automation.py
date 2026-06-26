"""Tests de la lógica de negocio pura de la pre-liquidación."""
from app.services.settlement_automation_service import (
    compute_datos_calculados,
    compute_ingreso_horario,
)


# --- Ingreso horario (corazón de la corrección: covarianza generación/precio) ---

def test_ingreso_horario_uses_hourly_covariance_not_average():
    """
    `generación_total × precio_promedio` ≠ Σ(gen_h × precio_h) cuando el perfil
    no es plano. La generación solar es diurna; el precio varía hora a hora.
    """
    # Hora 1: 10 kWh a 100 COP/kWh. Hora 2: 0 kWh a 300 COP/kWh (precio alto sin sol).
    horas = [(10.0, 100.0), (0.0, 300.0)]
    ingreso, horas_val, gen_val = compute_ingreso_horario(horas)

    # Correcto (horario): 10*100 + 0*300 = 1000.
    assert ingreso == 1000.0
    assert horas_val == 2
    assert gen_val == 10.0

    # El método ingenuo (total × promedio) habría dado el doble — y es erróneo.
    gen_total = sum(g for g, _ in horas)                 # 10
    precio_prom = sum(p for _, p in horas) / len(horas)  # 200
    assert gen_total * precio_prom == 2000.0
    assert ingreso != gen_total * precio_prom


def test_ingreso_horario_skips_hours_without_price():
    ingreso, horas_val, gen_val = compute_ingreso_horario(
        [(5.0, 200.0), (7.0, None), (3.0, 100.0)]
    )
    assert ingreso == 5.0 * 200.0 + 3.0 * 100.0  # 1300; la hora sin precio se omite
    assert horas_val == 2
    assert gen_val == 8.0  # 5 + 3 (la hora None no aporta a la generación valorizada)


def test_ingreso_horario_no_priced_hours_is_none():
    ingreso, horas_val, gen_val = compute_ingreso_horario([(5.0, None), (7.0, None)])
    assert ingreso is None  # ingreso desconocido, no cero
    assert horas_val == 0
    assert gen_val == 0.0


# --- Ensamblado del payload datos_calculados ---

def test_compute_basic_payload_and_deviation():
    datos = compute_datos_calculados(
        generacion_real_kwh=1000.0,
        horas_con_datos=24,
        ingreso_estimado_cop=250000.0,
        horas_valorizadas=24,
        generacion_valorizada_kwh=1000.0,
        precio_ponderado_cop_kwh=250.0,
        generacion_esperada_kwh=800.0,
    )
    assert datos["generacion_real_kwh"] == 1000.0
    assert datos["ingreso_estimado_cop"] == 250000.0
    assert datos["precio_bolsa_ponderado_cop_kwh"] == 250.0
    assert datos["generacion_valorizada_kwh"] == 1000.0
    assert datos["horas_valorizadas"] == 24
    assert datos["cobertura_precio_pct"] == 100.0
    assert datos["desviacion_pct"] == 25.0  # (1000-800)/800*100
    assert datos["horas_con_datos"] == 24
    assert datos["fuente"] == "MEM/ASIC"
    assert datos["cumplimiento"] is None


def test_payload_identity_closes_under_partial_price_coverage():
    """
    Con cobertura parcial de precios, el payload debe reconciliar exacto:
    ingreso = precio_ponderado × generacion_valorizada, y la generación NO
    valorizada (real − valorizada) debe ser derivable por el revisor.
    """
    datos = compute_datos_calculados(
        generacion_real_kwh=1000.0,   # generó 1000 kWh...
        horas_con_datos=24,
        ingreso_estimado_cop=150000.0,
        horas_valorizadas=18,
        generacion_valorizada_kwh=600.0,  # ...pero solo 600 cayeron en horas con precio
        precio_ponderado_cop_kwh=250.0,
        generacion_esperada_kwh=None,
    )
    # Identidad: ingreso == precio_ponderado × generacion_valorizada
    assert (
        round(datos["precio_bolsa_ponderado_cop_kwh"] * datos["generacion_valorizada_kwh"], 2)
        == datos["ingreso_estimado_cop"]
    )
    # El revisor puede ver el faltante sin valorizar y la cobertura de precios.
    assert datos["generacion_real_kwh"] - datos["generacion_valorizada_kwh"] == 400.0
    assert datos["cobertura_precio_pct"] == 75.0  # 18/24


def test_compute_without_price_yields_no_revenue():
    datos = compute_datos_calculados(
        generacion_real_kwh=500.0,
        horas_con_datos=12,
        ingreso_estimado_cop=None,
        horas_valorizadas=0,
        generacion_valorizada_kwh=0.0,
        precio_ponderado_cop_kwh=None,
        generacion_esperada_kwh=None,
    )
    assert datos["ingreso_estimado_cop"] is None
    assert datos["precio_bolsa_ponderado_cop_kwh"] is None
    assert datos["generacion_valorizada_kwh"] == 0.0
    assert datos["horas_valorizadas"] == 0
    assert datos["cobertura_precio_pct"] == 0.0
    assert datos["desviacion_pct"] is None
    assert datos["generacion_esperada_kwh"] is None


def test_compute_zero_expected_does_not_divide():
    datos = compute_datos_calculados(
        generacion_real_kwh=100.0,
        horas_con_datos=4,
        ingreso_estimado_cop=10000.0,
        horas_valorizadas=4,
        generacion_valorizada_kwh=100.0,
        precio_ponderado_cop_kwh=100.0,
        generacion_esperada_kwh=0.0,
    )
    assert datos["desviacion_pct"] is None  # esperada 0 → no se divide
    assert datos["ingreso_estimado_cop"] == 10000.0


def test_compute_carries_cumplimiento_payload():
    cumplimiento = {"contrato_ppa_id": 7, "compromiso_mwh": 90.0, "estado": "pendiente"}
    datos = compute_datos_calculados(
        generacion_real_kwh=1.0,
        horas_con_datos=1,
        ingreso_estimado_cop=1.0,
        horas_valorizadas=1,
        generacion_valorizada_kwh=1.0,
        precio_ponderado_cop_kwh=1.0,
        generacion_esperada_kwh=None,
        cumplimiento=cumplimiento,
    )
    assert datos["cumplimiento"] == cumplimiento


# --- Señal humana de cobertura (evita confundir parcial con completa) ---

def test_estado_cobertura_completa():
    datos = compute_datos_calculados(
        generacion_real_kwh=1000.0, horas_con_datos=24, ingreso_estimado_cop=250000.0,
        horas_valorizadas=24, generacion_valorizada_kwh=1000.0,
        precio_ponderado_cop_kwh=250.0, generacion_esperada_kwh=900.0,
    )
    assert datos["estado_cobertura"] == "completa"
    assert datos["avisos"] == []


def test_estado_cobertura_parcial_emite_aviso():
    datos = compute_datos_calculados(
        generacion_real_kwh=1000.0, horas_con_datos=24, ingreso_estimado_cop=150000.0,
        horas_valorizadas=18, generacion_valorizada_kwh=600.0,
        precio_ponderado_cop_kwh=250.0, generacion_esperada_kwh=900.0,
    )
    assert datos["estado_cobertura"] == "parcial"
    assert datos["cobertura_precio_pct"] == 75.0
    assert any("PARCIAL" in a for a in datos["avisos"])
    assert any("400.0 kWh" in a for a in datos["avisos"])  # 1000 - 600 sin valorizar


def test_estado_cobertura_sin_precio_marca_desconocido():
    datos = compute_datos_calculados(
        generacion_real_kwh=500.0, horas_con_datos=12, ingreso_estimado_cop=None,
        horas_valorizadas=0, generacion_valorizada_kwh=0.0,
        precio_ponderado_cop_kwh=None, generacion_esperada_kwh=None,
    )
    assert datos["estado_cobertura"] == "sin_precio"
    assert datos["ingreso_estimado_cop"] is None
    assert any("DESCONOCIDO" in a for a in datos["avisos"])
    assert any("línea base P50" in a for a in datos["avisos"])
