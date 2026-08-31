"""Tests de _tipos_superados (app.services.mgs.scheduler), sin BD -- función
pura que detecta qué alarmas el motor descartó internamente entre un
evaluate() y el siguiente, sin haber emitido una Alarm explícita (caso
SIN_GENERACION: ver auditoría alarmas_monitoreo 2026-08-31)."""
from app.services.mgs.alarm_engine import AlarmType
from app.services.mgs.scheduler import _tipos_superados


def test_sin_cambios_no_supera_nada():
    prev = {"Proyecto A": {AlarmType.PLANTA_CAIDA}}
    curr = {"Proyecto A": {AlarmType.PLANTA_CAIDA}}
    assert _tipos_superados(prev, curr) == {}


def test_proyecto_recupera_generacion_supera_sin_generacion():
    prev = {"Proyecto A": {AlarmType.SIN_GENERACION}}
    curr = {"Proyecto A": set()}
    assert _tipos_superados(prev, curr) == {"Proyecto A": {AlarmType.SIN_GENERACION}}


def test_proyecto_ya_no_reportado_por_el_motor_supera_todo():
    """Si el proyecto deja de aparecer en active_alarms (ej. Quoia dejó de
    listar el nodo), curr.get(key, set()) da vacío -- también debe cerrarse."""
    prev = {"Proyecto A": {AlarmType.PLANTA_CAIDA, AlarmType.SIN_GENERACION}}
    curr = {}
    assert _tipos_superados(prev, curr) == {
        "Proyecto A": {AlarmType.PLANTA_CAIDA, AlarmType.SIN_GENERACION}
    }


def test_solo_un_tipo_se_supera_el_otro_sigue_activo():
    prev = {"Proyecto A": {AlarmType.PLANTA_CAIDA, AlarmType.SIN_GENERACION}}
    curr = {"Proyecto A": {AlarmType.PLANTA_CAIDA}}
    assert _tipos_superados(prev, curr) == {"Proyecto A": {AlarmType.SIN_GENERACION}}


def test_proyecto_nuevo_sin_historial_no_revienta():
    prev = {}
    curr = {"Proyecto A": {AlarmType.PLANTA_CAIDA}}
    assert _tipos_superados(prev, curr) == {}
