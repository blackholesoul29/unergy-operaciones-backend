"""Falla.sla_limite_horas_efectivo (app.models.fallas) -- auditoría 2026-09-02.

sla_limite_horas está poblado en el 0.06% de las fallas (4/6444): el campo
sirve para casos puntuales que se salen del SLA estándar de su prioridad,
pero no hay ningún input en el frontend para escribirlo, así que la UI
mostraba "Sin límite" casi siempre aunque el cálculo de sla_cumplido
funcionara bien por debajo con el default. Esta propiedad expone ese mismo
cálculo (sla_limite_horas o el default por prioridad) para que el frontend
siempre tenga un número real que mostrar, sin duplicar la regla ni tocar
el dato guardado -- ver DEFAULT_SLA_HOURS, compartida con
_sincronizar_resolucion() en app/api/v1/fallas.py."""
from app.models.fallas import Falla, FallaCatPrioridad, DEFAULT_SLA_HOURS


def _falla(sla_limite_horas=None, nivel=None):
    f = Falla(sla_limite_horas=sla_limite_horas)
    f.prioridad = FallaCatPrioridad(nivel=nivel) if nivel is not None else None
    return f


def test_usa_el_override_si_existe_sin_importar_la_prioridad():
    f = _falla(sla_limite_horas=16, nivel=1)  # crítica default sería 8
    assert f.sla_limite_horas_efectivo == 16


def test_sin_override_cae_al_default_de_su_prioridad():
    for nivel, horas in DEFAULT_SLA_HOURS.items():
        assert _falla(sla_limite_horas=None, nivel=nivel).sla_limite_horas_efectivo == horas


def test_sin_override_y_sin_prioridad_cae_al_default_generico():
    assert _falla(sla_limite_horas=None, nivel=None).sla_limite_horas_efectivo == 72


def test_nivel_desconocido_cae_al_default_generico():
    assert _falla(sla_limite_horas=None, nivel=99).sla_limite_horas_efectivo == 72
