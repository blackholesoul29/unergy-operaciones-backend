"""Cobertura de garantías: funciones puras de cálculo y clasificación de alerta.

Semántica (ver garantia_coverage_service):
- cobertura = valor_actual / valor_requerido (más alta = mejor).
- Los umbrales son pisos de cobertura; la ROJA es el piso más estricto (menor).
  Con los defaults (roja=0.90, amarilla=0.95): <0.90 ROJO, <0.95 AMARILLO,
  ≥0.95 VERDE. Sin exposición (valor_requerido<=0) → cobertura None → VERDE.
  Config invertida (legado): min()/max() interno la reordena como red de seguridad.
"""
from app.services.garantia_coverage_service import (
    calcular_valor_requerido,
    calcular_cobertura_porcentaje,
    clasificar_nivel_alerta,
    evaluar_cobertura,
    FACTOR_EXPOSICION_DEFAULT,
)


def test_valor_requerido_formula_placeholder():
    # 100_000 kWh * 300 COP/kWh * 0.1 = 3_000_000
    assert calcular_valor_requerido(100_000, 300) == 100_000 * 300 * FACTOR_EXPOSICION_DEFAULT
    assert calcular_valor_requerido(100_000, 300) == 3_000_000


def test_valor_requerido_no_negativo():
    assert calcular_valor_requerido(-50, 300) == 0.0
    assert calcular_valor_requerido(100, -10) == 0.0


def test_cobertura_porcentaje_basica():
    assert calcular_cobertura_porcentaje(3_000_000, 3_000_000) == 1.0
    assert calcular_cobertura_porcentaje(2_700_000, 3_000_000) == 0.9


def test_cobertura_requerido_cero_es_none():
    assert calcular_cobertura_porcentaje(1_000, 0) is None
    assert calcular_cobertura_porcentaje(1_000, -5) is None


def test_clasificacion_verde():
    # cobertura 1.0 ≥ 0.95 → VERDE
    assert clasificar_nivel_alerta(1.0, 0.95, 0.90) == "VERDE"
    assert clasificar_nivel_alerta(0.95, 0.95, 0.90) == "VERDE"


def test_clasificacion_amarillo():
    # 0.90 ≤ cobertura < 0.95 → AMARILLO
    assert clasificar_nivel_alerta(0.92, 0.95, 0.90) == "AMARILLO"
    assert clasificar_nivel_alerta(0.90, 0.95, 0.90) == "AMARILLO"


def test_clasificacion_rojo():
    # cobertura < 0.90 → ROJO
    assert clasificar_nivel_alerta(0.89, 0.95, 0.90) == "ROJO"
    assert clasificar_nivel_alerta(0.5, 0.90, 0.95) == "ROJO"


def test_clasificacion_none_es_verde():
    assert clasificar_nivel_alerta(None, 0.90, 0.95) == "VERDE"


def test_clasificacion_robusta_al_orden_de_umbrales():
    # Aunque se pasen invertidos, la línea roja es siempre la más estricta.
    assert clasificar_nivel_alerta(0.89, 0.95, 0.90) == "ROJO"
    assert clasificar_nivel_alerta(0.92, 0.95, 0.90) == "AMARILLO"


def test_evaluar_cobertura_bien_cubierta():
    # valor_requerido = 100_000*300*0.1 = 3_000_000; actual 3_500_000 → cobertura ~1.17
    res = evaluar_cobertura(
        valor_actual=3_500_000,
        generacion_kwh_30d=100_000,
        precio_promedio_cop_kwh=300,
        umbral_amarilla=0.90,
        umbral_roja=0.95,
    )
    assert res["valor_requerido"] == 3_000_000
    assert res["nivel_alerta"] == "VERDE"
    assert res["cobertura_porcentaje"] > 1.0
    assert res["detalles_calculo"]["generacion_kwh_30d"] == 100_000


def test_evaluar_cobertura_alerta_amarilla():
    # actual 2_760_000 / 3_000_000 = 0.92 → AMARILLO
    res = evaluar_cobertura(
        valor_actual=2_760_000,
        generacion_kwh_30d=100_000,
        precio_promedio_cop_kwh=300,
        umbral_amarilla=0.90,
        umbral_roja=0.95,
    )
    assert res["nivel_alerta"] == "AMARILLO"
    assert res["cobertura_porcentaje"] == 0.92


def test_evaluar_cobertura_alerta_roja():
    # actual 2_400_000 / 3_000_000 = 0.80 → ROJO
    res = evaluar_cobertura(
        valor_actual=2_400_000,
        generacion_kwh_30d=100_000,
        precio_promedio_cop_kwh=300,
        umbral_amarilla=0.90,
        umbral_roja=0.95,
    )
    assert res["nivel_alerta"] == "ROJO"
    assert res["cobertura_porcentaje"] == 0.80


def test_evaluar_cobertura_sin_exposicion_es_verde():
    res = evaluar_cobertura(
        valor_actual=1_000_000,
        generacion_kwh_30d=0,
        precio_promedio_cop_kwh=300,
        umbral_amarilla=0.90,
        umbral_roja=0.95,
    )
    assert res["valor_requerido"] == 0
    assert res["cobertura_porcentaje"] is None
    assert res["nivel_alerta"] == "VERDE"


def test_config_invertida_se_reordena_como_red_de_seguridad():
    # Datos legados con umbrales cruzados (roja > amarilla): el clasificador
    # los reordena internamente y la severidad no se degrada.
    assert clasificar_nivel_alerta(0.89, 0.90, 0.95) == "ROJO"
    assert clasificar_nivel_alerta(0.92, 0.90, 0.95) == "AMARILLO"
    assert clasificar_nivel_alerta(0.96, 0.90, 0.95) == "VERDE"


def test_schema_rechaza_roja_mayor_que_amarilla():
    import pytest
    from pydantic import ValidationError
    from app.schemas.garantia_cobertura import GarantiaMonitoreoConfig

    with pytest.raises(ValidationError):
        GarantiaMonitoreoConfig(umbral_alerta_roja=0.95, umbral_alerta_amarilla=0.90)
    ok = GarantiaMonitoreoConfig(umbral_alerta_roja=0.90, umbral_alerta_amarilla=0.95)
    assert ok.umbral_alerta_roja == 0.90
