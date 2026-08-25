"""FronteraCreate/Update -- rangos numericos (latitud/longitud, capacidades
no negativas, factor_perdidas) para atrapar typos de digitacion antes de
llegar a la BD (punto 5 del diagnostico de integridad de Fronteras,
2026-08-25). Respaldados por CHECK constraints en la BD (migracion 084)
para el caso de que un dato entre por otro camino."""
import pytest
from pydantic import ValidationError

from app.schemas.fronteras import FronteraCreate, FronteraUpdate


def test_latitud_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", latitud=950)


def test_longitud_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", longitud=-1800)


def test_latitud_longitud_validas_se_aceptan():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", latitud=8.5, longitud=-73.2)
    assert f.latitud == 8.5
    assert f.longitud == -73.2


def test_potencia_maxima_declarada_negativa_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", potencia_maxima_declarada=-5)


def test_factor_perdidas_fuera_de_rango_se_rechaza():
    # factor_perdidas es un multiplicador (~1.0-1.05 en produccion), no una
    # fraccion 0-1 -- un valor de 0 o negativo no tiene sentido fisico.
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", factor_perdidas=0)


def test_factor_perdidas_valido_se_acepta():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", factor_perdidas=1.02)
    assert f.factor_perdidas == 1.02


def test_update_tambien_valida_rangos():
    with pytest.raises(ValidationError):
        FronteraUpdate(latitud=100)
    with pytest.raises(ValidationError):
        FronteraUpdate(potencia_maxima_declarada=-1)
