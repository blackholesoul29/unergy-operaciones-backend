"""Tests de la decisión de alarmas de comunicación (función pura)."""
from app.services.fallas.alarmas import decidir_alarmas


def test_sin_perdidas_no_alarma():
    assert decidir_alarmas(False, False) == []


def test_solo_frontera():
    assert decidir_alarmas(True, False) == ["comunicacion_frontera"]


def test_solo_inversores():
    assert decidir_alarmas(False, True) == ["comunicacion_inversores"]


def test_ambas_genera_critica_total():
    out = decidir_alarmas(True, True)
    assert out == ["comunicacion_frontera", "comunicacion_inversores", "comunicacion_total"]
    assert "comunicacion_total" in out  # alarma crítica de pérdida total
