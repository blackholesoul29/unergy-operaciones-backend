"""Cuál contrato de representación manda cuando hay varios.

Un proyecto puede tener más de uno -- 66 filas para 38 proyectos -- y algunos con
tarifas contradictorias: Joropo tiene tres, dos con las tarifas en cero y uno en 5.

Hoy gana el de menor `id`, que da la casualidad de ser el correcto en los 38
proyectos (el 108 de Joropo, con tarifa 5, tiene id menor que los dos de ceros).
Estas pruebas fijan la regla para que deje de depender de esa casualidad: basta
que alguien borre el 108 o cree uno con id menor para que empiece a leer ceros.
"""
import types

from app.services.costos_panel import elegir_contrato_representacion


def _c(id_, estado="vigente", rep=5.0, cgm=5.0, admin=0.038):
    return types.SimpleNamespace(id=id_, estado=estado, tarifa_representacion=rep,
                                 tarifa_cgm=cgm, tarifa_admin=admin)


def test_prefiere_el_vigente():
    assert elegir_contrato_representacion([
        _c(9, estado="terminado"), _c(2, estado="vigente")]).id == 2


def test_entre_vigentes_prefiere_el_que_tiene_tarifas():
    """El caso Joropo, con los ids invertidos: el de ceros ya no debe ganar."""
    assert elegir_contrato_representacion([
        _c(210, rep=5.0, cgm=5.0), _c(108, rep=0.0, cgm=0.0)]).id == 210


def test_el_orden_actual_de_joropo_sigue_dando_lo_mismo():
    """Con los ids reales de hoy la respuesta no cambia: 108 tiene la tarifa."""
    assert elegir_contrato_representacion([
        _c(108, rep=5.0, cgm=5.0), _c(209, rep=0.0, cgm=0.0),
        _c(210, rep=0.0, cgm=0.0)]).id == 108


def test_a_igualdad_de_condiciones_gana_el_mas_reciente():
    assert elegir_contrato_representacion([_c(1), _c(9), _c(4)]).id == 9


def test_una_tarifa_de_admin_sola_ya_cuenta_como_tarifa():
    """Los proyectos GD tienen repre y CGM pero no admin, y al revés también pasa."""
    assert elegir_contrato_representacion([
        _c(1, rep=0.0, cgm=0.0, admin=None),
        _c(2, rep=0.0, cgm=0.0, admin=0.038)]).id == 2


def test_sin_contratos_devuelve_none():
    assert elegir_contrato_representacion([]) is None


def test_si_ninguno_esta_vigente_igual_devuelve_uno():
    """Mejor la tarifa de un contrato terminado que ninguna: quien llama decide
    después si la usa."""
    assert elegir_contrato_representacion([
        _c(1, estado="terminado"), _c(5, estado="terminado")]).id == 5


def test_un_vigente_sin_tarifas_pierde_contra_un_terminado_con_tarifas():
    """La vigencia manda sobre tener tarifa: un contrato vigente en ceros es una
    decisión de negocio, no un dato faltante."""
    assert elegir_contrato_representacion([
        _c(1, estado="terminado", rep=6.0), _c(2, estado="vigente", rep=0.0,
                                               cgm=0.0, admin=None)]).id == 2
