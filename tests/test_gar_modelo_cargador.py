"""Carga de insumos FTP: idempotencia y la regla de disponible_desde."""
import datetime

import pytest

from app.services.garantias_modelo.cargador import (
    LAG_POR_VERSION,
    disponible_desde_derivado,
    filas_a_medidas,
)

FECHA = datetime.date(2026, 8, 14)


def test_lag_de_tx2_es_siete_dias():
    """Sale del timeline de XM: la ventana cierra 14 días antes del vencimiento y XM
    calcula 7 días antes, usando TX2 de esos días."""
    assert LAG_POR_VERSION["tx2"] == 7


def test_disponible_desde_derivado_suma_el_lag():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.date() == datetime.date(2026, 8, 21)


def test_disponible_desde_derivado_es_utc():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.tzinfo is not None


def test_version_sin_lag_conocido_falla_ruidosamente():
    """Errar por exceso es seguro, inventar no. Una versión desconocida se rechaza."""
    with pytest.raises(ValueError):
        disponible_desde_derivado(FECHA, "txz")


def test_filas_a_medidas_asigna_el_archivo():
    filas = [{"tipo": "trsd", "fecha_documento": FECHA, "hora": 1, "entidad": "NACIONAL",
              "concepto": "pbna", "concepto_raw": "PBNA", "valor": 250.5, "version": "tx2"}]
    r = filas_a_medidas(filas, archivo_id=42)
    assert len(r) == 1
    assert r[0]["archivo_id"] == 42
    assert r[0]["concepto"] == "pbna"


def test_filas_a_medidas_vacio():
    assert filas_a_medidas([], archivo_id=1) == []
