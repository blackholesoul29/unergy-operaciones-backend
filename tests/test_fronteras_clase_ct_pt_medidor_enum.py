"""clase_ct/clase_pt/clase_medidor -- pasaron de texto libre a Enum real
(migracion 096, 2026-08-25). Antes cualquier string pasaba la validacion de
Pydantic sin problema y solo fallaba (o peor, quedaba guardado) al escribir
en la BD. Acotados a las clases de precision de metrologia YA en uso en
produccion, no al catalogo completo de la norma (a pedido de Sara)."""
import pytest
from pydantic import ValidationError

from app.schemas.fronteras import FronteraCreate, FronteraUpdate


def test_clase_ct_valida_se_acepta():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_ct="0.5s")
    assert f.clase_ct == "0.5s"


def test_clase_ct_invalida_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_ct="1.0")


def test_clase_pt_valida_se_acepta():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_pt="0.2")
    assert f.clase_pt == "0.2"


def test_clase_pt_invalida_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_pt="0.5s")


def test_clase_medidor_valida_se_acepta():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_medidor="0.2s")
    assert f.clase_medidor == "0.2s"


def test_clase_medidor_invalida_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", clase_medidor="0.2")


def test_update_tambien_valida_las_3_clases():
    with pytest.raises(ValidationError):
        FronteraUpdate(clase_ct="invalido")
    with pytest.raises(ValidationError):
        FronteraUpdate(clase_pt="invalido")
    with pytest.raises(ValidationError):
        FronteraUpdate(clase_medidor="invalido")
