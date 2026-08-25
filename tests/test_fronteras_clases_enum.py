"""Las clases de precisión de una frontera se guardan por VALOR, no por nombre.

Los tipos de Postgres tienen las etiquetas "0.2", "0.2s", "0.5s" -- el valor del
miembro-- y así están las 94 filas. SQLAlchemy usa el NOMBRE (`clase_0_5s`) salvo
que se le pase `values_callable`, y sin eso al leer revienta con

    LookupError: '0.5s' is not among the defined enum values

lo que tumbaba con 500 cualquier consulta que cargara fronteras, incluida la lista
de proyectos, que las trae con selectinload.
"""
import pytest
from sqlalchemy import Enum as SAEnum

from app.models.fronteras import (
    ClaseCtEnum, ClaseMedidorEnum, ClasePtEnum, Frontera,
)

COLUMNAS = [
    ("clase_ct", ClaseCtEnum, {"0.2", "0.2s", "0.5s"}),
    ("clase_pt", ClasePtEnum, {"0.2", "0.5"}),
    ("clase_medidor", ClaseMedidorEnum, {"0.2s", "0.5s"}),
]


@pytest.mark.parametrize("columna,enum_cls,etiquetas", COLUMNAS)
def test_la_columna_guarda_los_valores_no_los_nombres(columna, enum_cls, etiquetas):
    """Lo que viaja a Postgres tiene que coincidir con las etiquetas del tipo."""
    tipo = Frontera.__table__.c[columna].type
    assert isinstance(tipo, SAEnum)
    assert set(tipo.enums) == etiquetas


@pytest.mark.parametrize("columna,enum_cls,etiquetas", COLUMNAS)
def test_ningun_valor_es_el_nombre_del_miembro(columna, enum_cls, etiquetas):
    """`clase_0_5s` en la lista significaría que volvió el desajuste."""
    tipo = Frontera.__table__.c[columna].type
    assert not any(e.startswith("clase_") for e in tipo.enums)


@pytest.mark.parametrize("columna,enum_cls,etiquetas", COLUMNAS)
def test_se_puede_leer_un_valor_guardado(columna, enum_cls, etiquetas):
    """Es la operación que fallaba: convertir lo que viene de la BD al enum."""
    tipo = Frontera.__table__.c[columna].type
    leer = tipo.result_processor(None, None)
    for etiqueta in etiquetas:
        assert leer(etiqueta) is not None, etiqueta
