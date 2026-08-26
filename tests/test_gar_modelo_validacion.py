"""validar_esquema: detecta archivos corruptos ANTES de que entren a xm_medida."""
from app.services.garantias_modelo.validacion import (
    validar_estructura,
    verificar_identidad_balcttos,
)


def _cab(cols):
    return (";".join(cols) + "\n" + ";".join(["0"] * len(cols)) + "\n").encode("latin1")


HORAS = [f"HORA {h:02d}" for h in range(1, 25)]
BASE = ["CONCEPTO", "MERCADO", "CÓDIGO CONTRATO", "COMPRADOR", "VENDEDOR",
        "TIPO DE DESPACHO", "TIPO ASIGNA"]


def test_estructura_valida_pasa():
    ok, detalle = validar_estructura(_cab(BASE + HORAS), "balcttos")
    assert ok, detalle


def test_columna_duplicada_se_rechaza():
    # El caso real de abril-2026: sin esto el signo se invierte en silencio.
    ok, detalle = validar_estructura(_cab(BASE + HORAS + ["HORA 24"]), "balcttos")
    assert not ok
    assert "duplicad" in detalle["motivo"].lower()


def test_faltan_horas_se_rechaza():
    ok, detalle = validar_estructura(_cab(BASE + HORAS[:20]), "balcttos")
    assert not ok
    assert detalle["horas_encontradas"] == 20


def test_archivo_vacio_se_rechaza():
    ok, detalle = validar_estructura(b"", "balcttos")
    assert not ok


def test_identidad_balcttos_cierra():
    # GI - contratos - perdidas == ventas - compras
    ok, resid = verificar_identidad_balcttos(
        generacion_ideal=100.0, contratos_venta=80.0, perdidas=5.0,
        neto_ventas=20.0, neto_compras=5.0)
    assert ok
    assert abs(resid) < 0.01


def test_identidad_balcttos_no_cierra_se_reporta():
    ok, resid = verificar_identidad_balcttos(
        generacion_ideal=100.0, contratos_venta=80.0, perdidas=5.0,
        neto_ventas=50.0, neto_compras=5.0)
    assert not ok
    assert abs(resid) > 0.01
