"""Validación de rangos O&M: formato de periodo, rango de año, tope de tasa IPC."""
import pytest
from pydantic import ValidationError

from app.utils.periodo import periodo_valido, anio_valido
from app.schemas.om import IPCTasaUpsert


# ── periodo_valido (YYYY-MM estricto) ─────────────────────────────────────────

def test_periodo_valido_formato_correcto():
    assert periodo_valido("2026-06") is True
    assert periodo_valido("2026-01") is True
    assert periodo_valido("2026-12") is True


def test_periodo_invalido_mes_sin_cero():
    # "2026-6" != "2026-06": el UniqueConstraint los ve distintos → hay que rechazarlo.
    assert periodo_valido("2026-6") is False


def test_periodo_invalido_mes_fuera_de_rango():
    assert periodo_valido("2026-13") is False
    assert periodo_valido("2026-00") is False


def test_periodo_invalido_basura():
    assert periodo_valido("abc") is False
    assert periodo_valido("") is False
    assert periodo_valido(None) is False
    assert periodo_valido("2026/06") is False


# ── anio_valido ───────────────────────────────────────────────────────────────

def test_anio_valido_rango():
    assert anio_valido(2026) is True
    assert anio_valido(2000) is True
    assert anio_valido(2100) is True


def test_anio_invalido_fuera_de_rango():
    assert anio_valido(1500) is False
    assert anio_valido(3000) is False


# ── IPCTasaUpsert.tasa (tope de sanidad, fracción [-1, 1]) ────────────────────

def test_ipc_tasa_dentro_de_rango():
    assert IPCTasaUpsert(tasa=0.0928).tasa == 0.0928
    assert IPCTasaUpsert(tasa=-0.05).tasa == -0.05


def test_ipc_tasa_fuera_de_rango_rechaza():
    with pytest.raises(ValidationError):
        IPCTasaUpsert(tasa=2.0)
    with pytest.raises(ValidationError):
        IPCTasaUpsert(tasa=-1.5)
