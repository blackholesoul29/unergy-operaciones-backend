"""calcular_alerta: contador de días sin respuesta del CRM comercial.

Función pura — la referencia es max(estado_desde, última gestión).
Alerta solo en etapas activas (oportunidad/oferta/contrato) y solo con
MÁS de `umbral_dias` días (el día exacto del umbral NO alerta). Fin nunca
alerta (decisión de spec: migrar históricos a Fin no debe generar ruido).
"""
from datetime import datetime, timedelta, timezone

from app.services.comercial import calcular_alerta, ESTADOS_CON_ALERTA

AHORA = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def _hace(dias: int) -> datetime:
    return AHORA - timedelta(days=dias)


def test_sin_gestiones_supera_umbral():
    dias, alerta = calcular_alerta("oportunidad", _hace(6), None, 5, AHORA)
    assert (dias, alerta) == (6, True)


def test_umbral_exacto_no_alerta():
    dias, alerta = calcular_alerta("oferta", _hace(5), None, 5, AHORA)
    assert (dias, alerta) == (5, False)


def test_gestion_reciente_reinicia_contador():
    # Estado viejo (20 días) pero gestión de hace 2 → no alerta.
    dias, alerta = calcular_alerta("negociacion", _hace(20), _hace(2), 5, AHORA)
    assert (dias, alerta) == (2, False)


def test_gestion_anterior_al_cambio_de_estado_no_cuenta():
    # La gestión es más vieja que la entrada al estado → manda estado_desde.
    dias, alerta = calcular_alerta("oferta", _hace(7), _hace(30), 5, AHORA)
    assert (dias, alerta) == (7, True)


def test_fin_nunca_alerta():
    dias, alerta = calcular_alerta("fin", _hace(400), None, 5, AHORA)
    assert dias == 400
    assert alerta is False


def test_estados_con_alerta_son_los_tres_activos():
    assert ESTADOS_CON_ALERTA == frozenset({"oportunidad", "oferta", "contrato"})


def test_umbral_configurable():
    # Con umbral 10, 8 días no alertan; con umbral 5 sí.
    assert calcular_alerta("oportunidad", _hace(8), None, 10, AHORA)[1] is False
    assert calcular_alerta("oportunidad", _hace(8), None, 5, AHORA)[1] is True


def test_referencia_futura_no_da_dias_negativos():
    dias, alerta = calcular_alerta("oportunidad", AHORA + timedelta(days=1), None, 5, AHORA)
    assert (dias, alerta) == (0, False)
