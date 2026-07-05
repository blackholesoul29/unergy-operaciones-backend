"""Tests de validación de los schemas de configuración operativa.

Cubren el hardening sobre el estimador de impacto económico: los parámetros
alimentan cálculos de dinero, así que un valor fuera de rango físico (factor de
capacidad > 1, precio ≤ 0) debe rechazarse en el borde (422) en vez de corromper
silenciosamente las estimaciones. También `unidad` acotada al ancho de columna.
"""
import pytest
from pydantic import ValidationError

from app.models.configuracion_operativa import TipoParametroConfigEnum
from app.schemas.configuracion_operativa import (
    ConfiguracionOperativaCreate,
    ConfiguracionOperativaUpdate,
    validar_rango_por_tipo,
)

FACTOR = TipoParametroConfigEnum.CAPACIDAD_SOLAR
PRECIO = TipoParametroConfigEnum.PRECIO_ENERGIA


def _create(**kw):
    base = dict(tipo_parametro=FACTOR, valor_float=0.18, unidad="factor")
    base.update(kw)
    return ConfiguracionOperativaCreate(**base)


# --- CAPACIDAD_SOLAR: factor físico en (0, 1] ---

def test_factor_valido_ok():
    cfg = _create(tipo_parametro=FACTOR, valor_float=0.18)
    assert cfg.valor_float == 0.18


def test_factor_uno_ok_limite_superior():
    assert _create(tipo_parametro=FACTOR, valor_float=1.0).valor_float == 1.0


def test_factor_mayor_que_uno_rechazado():
    with pytest.raises(ValidationError):
        _create(tipo_parametro=FACTOR, valor_float=5.0)


def test_factor_cero_rechazado():
    with pytest.raises(ValidationError):
        _create(tipo_parametro=FACTOR, valor_float=0.0)


# --- PRECIO_ENERGIA: COP/kWh > 0 ---

def test_precio_valido_ok():
    cfg = _create(tipo_parametro=PRECIO, valor_float=800.0, unidad="COP/kWh")
    assert cfg.valor_float == 800.0


def test_precio_cero_rechazado():
    with pytest.raises(ValidationError):
        _create(tipo_parametro=PRECIO, valor_float=0.0, unidad="COP/kWh")


def test_precio_negativo_rechazado():
    with pytest.raises(ValidationError):
        _create(tipo_parametro=PRECIO, valor_float=-1.0, unidad="COP/kWh")


# --- unidad acotada a VARCHAR(20) ---

def test_unidad_larga_rechazada():
    with pytest.raises(ValidationError):
        _create(unidad="x" * 21)


def test_unidad_veinte_ok():
    assert _create(unidad="x" * 20).unidad == "x" * 20


# --- helper reutilizable (usado también por el endpoint de update) ---

def test_validar_rango_por_tipo_directo():
    validar_rango_por_tipo(FACTOR, 0.5)          # no lanza
    validar_rango_por_tipo(PRECIO, 800.0)        # no lanza
    with pytest.raises(ValueError):
        validar_rango_por_tipo(FACTOR, 1.5)
    with pytest.raises(ValueError):
        validar_rango_por_tipo(PRECIO, 0.0)


# --- Update parcial: no valida rango por tipo (el endpoint lo hace), pero sí no-negativo ---

def test_update_valor_negativo_rechazado():
    with pytest.raises(ValidationError):
        ConfiguracionOperativaUpdate(valor_float=-5.0)


def test_update_unidad_larga_rechazada():
    with pytest.raises(ValidationError):
        ConfiguracionOperativaUpdate(unidad="x" * 21)


def test_update_parcial_valido_ok():
    upd = ConfiguracionOperativaUpdate(valor_float=0.2)
    assert upd.valor_float == 0.2
    assert upd.unidad is None
