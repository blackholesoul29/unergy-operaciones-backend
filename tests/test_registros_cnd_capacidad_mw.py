"""_capacidad_mw() (registros_cnd/correos.py) -- tenía un fallback intermedio
a Proyecto.capacidad_efectiva_neta_mw, un campo que nunca existió en el
modelo (getattr(..., None) siempre caía a None, así que era muerto en la
práctica). Auditoría de Proyectos 2026-08-27, hallazgo #4."""
from types import SimpleNamespace

from app.services.registros_cnd.correos import _capacidad_mw


def test_usa_potencia_con_cen_mw_si_existe():
    p = SimpleNamespace(potencia_con_cen_mw=2.5, potencia_instalada_kwp=990.0)
    assert _capacidad_mw(p) == "2.500"


def test_cae_a_potencia_instalada_kwp_convertida_a_mw():
    p = SimpleNamespace(potencia_con_cen_mw=None, potencia_instalada_kwp=990.0)
    assert _capacidad_mw(p) == "0.990"


def test_placeholder_si_no_hay_ningun_dato():
    p = SimpleNamespace(potencia_con_cen_mw=None, potencia_instalada_kwp=None)
    assert _capacidad_mw(p) == "[X.XXX]"
