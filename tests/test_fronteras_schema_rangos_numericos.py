"""FronteraCreate/Update -- rangos numericos (capacidades no negativas,
factor_perdidas) para atrapar typos de digitacion antes de llegar a la BD
(punto 5 del diagnostico de integridad de Fronteras, 2026-08-25).
Respaldados por CHECK constraints en la BD (migracion 084) para el caso de
que un dato entre por otro camino.

latitud/longitud se consolidaron en Proyecto (migracion 094, 2026-08-25) --
sus tests de rango equivalentes viven ahora en
test_proyectos_schema_rangos_numericos.py."""
import pytest
from pydantic import ValidationError

from app.schemas.fronteras import FronteraCreate, FronteraUpdate


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
        FronteraUpdate(transferencia_maxima_kwh=-1)
    with pytest.raises(ValidationError):
        FronteraUpdate(potencia_maxima_declarada=-1)
