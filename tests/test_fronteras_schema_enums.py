"""FronteraCreate/Update.tipo_frontera y .estado -- usan los Enums reales
en vez de `str` plano (punto 10 del diagnóstico de Fronteras, 2026-08-24).

Antes, un valor inválido pasaba la validación de Pydantic sin problema y
solo fallaba al escribir en la BD (error crudo de SQLAlchemy/Postgres en
vez de un 422 con mensaje claro)."""
import pytest
from pydantic import ValidationError

from app.schemas.fronteras import FronteraCreate, FronteraUpdate, FronteraQuoiaConfirmar
from app.models.fronteras import TipoFronteraEnum, EstadoFronteraEnum


def test_tipo_frontera_invalido_se_rechaza_al_crear():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="no_existe")


def test_estado_invalido_se_rechaza_al_crear():
    with pytest.raises(ValidationError):
        FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", estado="no_existe")


def test_valores_validos_se_aceptan_como_texto_y_quedan_como_enum():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="generacion", estado="activa")
    assert f.tipo_frontera == TipoFronteraEnum.generacion
    assert f.estado == EstadoFronteraEnum.activa
    # Siguen comportándose como str (para lo que ya asume el resto del código).
    assert f.tipo_frontera == "generacion"


def test_estado_por_defecto_es_activa():
    f = FronteraCreate(nombre_frontera="Test", tipo_frontera="consumo")
    assert f.estado == EstadoFronteraEnum.activa


def test_update_tipo_frontera_invalido_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraUpdate(tipo_frontera="no_existe")


def test_confirmar_desde_quoia_tipo_frontera_invalido_se_rechaza():
    with pytest.raises(ValidationError):
        FronteraQuoiaConfirmar(proyecto_id=1, tipo_frontera="no_existe")
