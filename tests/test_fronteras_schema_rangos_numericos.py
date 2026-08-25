"""FronteraCreate/Update -- rangos numericos (capacidades no negativas)
para atrapar typos de digitacion antes de llegar a la BD (punto 5 del
diagnostico de integridad de Fronteras, 2026-08-25). Respaldados por
CHECK constraints en la BD (migracion 084) para el caso de que un dato
entre por otro camino.

latitud/longitud se consolidaron en Proyecto (migracion 094, 2026-08-25) --
sus tests de rango equivalentes viven ahora en
test_proyectos_schema_rangos_numericos.py.

factor_perdidas/potencia_maxima_declarada y los demas campos que tenian
rango validado aca se eliminaron de Frontera (migracion 097, 2026-08-25) --
sin equivalente en Proyecto, sin reemplazo."""
import pytest
from pydantic import ValidationError

from app.schemas.fronteras import FronteraUpdate


def test_update_tambien_valida_rangos():
    with pytest.raises(ValidationError):
        FronteraUpdate(transferencia_maxima_kwh=-1)
