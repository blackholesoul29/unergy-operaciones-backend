from datetime import date
from app.models.finanzas_mandatos import FinanzasMandato, TipoMandatoEnum, EstadoFirmaEnum


def test_modelo_campos_basicos():
    m = FinanzasMandato(
        proyecto="Minigranja Solar Baraya", tercero="SOLENIUM SAS",
        periodo=date(2026, 7, 1), tipo="costo", cmu="CMU0521", estado="sin_firma",
    )
    assert m.tipo == "costo"
    assert m.estado == "sin_firma"


def test_enums_valores():
    assert set(e.value for e in TipoMandatoEnum) == {"ingreso", "costo"}
    assert "firmado" in set(e.value for e in EstadoFirmaEnum)
    assert "con_comentarios" in set(e.value for e in EstadoFirmaEnum)
