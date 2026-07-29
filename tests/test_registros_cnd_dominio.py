"""Tests de la logica de dominio de "Registros CND/ASIC" (funciones puras).

Portados del prototipo (Next.js/TS, 52 tests). Cubren: ponderacion/avance, maquina
de estados, validaciones del 9.3 y motor de alertas. No tocan la base de datos.
"""

from datetime import date

from app.services.registros_cnd import dominio
from app.services.registros_cnd.avance import (
    HitoAvance, hitos_por_defecto, calcular_avance_pct, suma_pesos,
    avance_por_etapa, siguiente_hito_pendiente,
)
from app.services.registros_cnd import state_machine as sm
from app.services.registros_cnd.dominio import Estado, Etapa, Hito
from app.services.registros_cnd.validaciones_93 import (
    Entradas93, validar_93, corrientes_desde_in_eq,
)
from app.services.registros_cnd import alertas as al


# ---------------------------------------------------------------------------
# Avance / ponderacion
# ---------------------------------------------------------------------------
def test_pesos_suman_100():
    assert suma_pesos(hitos_por_defecto()) == 100.0
    assert sum(h["peso_default"] for h in dominio.HITOS) == 100


def test_avance_solo_cuenta_completados():
    hitos = hitos_por_defecto()
    assert calcular_avance_pct(hitos) == 0.0
    # completar 1a (8) y 1b (7) -> 15
    for h in hitos:
        if h.hito in (Hito.H_1A, Hito.H_1B):
            h.completado = True
    assert calcular_avance_pct(hitos) == 15.0


def test_avance_por_etapa():
    hitos = hitos_por_defecto()
    for h in hitos:
        if h.hito == Hito.H_1A:
            h.completado = True
    filas = {a.etapa: a for a in avance_por_etapa(hitos)}
    e1 = filas[Etapa.ETAPA_1_CREG174_AMBITO]
    assert e1.total_pct == 15.0  # 1a(8) + 1b(7)
    assert e1.ganado_pct == 8.0
    assert e1.completos == 1 and e1.total_hitos == 2


def test_siguiente_hito_pendiente_orden():
    hitos = hitos_por_defecto()
    assert siguiente_hito_pendiente(hitos) == Hito.H_1A
    for h in hitos:
        if h.hito == Hito.H_1A:
            h.completado = True
    assert siguiente_hito_pendiente(hitos) == Hito.H_1B


def test_siguiente_hito_none_si_todo_completo():
    hitos = hitos_por_defecto()
    for h in hitos:
        h.completado = True
    assert siguiente_hito_pendiente(hitos) is None


# ---------------------------------------------------------------------------
# Maquina de estados
# ---------------------------------------------------------------------------
def test_transicion_valida_e_invalida():
    assert sm.es_transicion_valida(Etapa.ETAPA_1_CREG174_AMBITO, Estado.NO_INICIADO, Estado.SOLICITUD_RADICADA)
    assert not sm.es_transicion_valida(Etapa.ETAPA_1_CREG174_AMBITO, Estado.NO_INICIADO, Estado.AMBITO_EMITIDO)


def test_hitos_al_entrar():
    assert sm.hitos_completados_al_entrar(Etapa.ETAPA_1_CREG174_AMBITO, Estado.CREG174_APROBADA) == [Hito.H_1A]
    assert sm.hitos_completados_al_entrar(Etapa.ETAPA_1_CREG174_AMBITO, Estado.AMBITO_EMITIDO) == [Hito.H_1B]
    assert sm.hitos_completados_al_entrar(Etapa.ETAPA_8_REQ_9_4, Estado.APROBADA_XM) == [Hito.H_8C]


def test_responsable_de_estado():
    assert sm.responsable_de_estado(Etapa.ETAPA_2_CARTAS_9_1_9_7, Estado.SOLICITUD_ENVIADA_OR) == dominio.Responsable.OR
    assert sm.responsable_de_estado(Etapa.ETAPA_6_FRONTERA, Estado.EQUIPOS_SOLICITADOS) == dominio.Responsable.SOLENIUM


def test_estado_final():
    assert sm.es_estado_final(Etapa.ETAPA_2_CARTAS_9_1_9_7, Estado.CARTAS_FIRMADAS)
    assert not sm.es_estado_final(Etapa.ETAPA_2_CARTAS_9_1_9_7, Estado.NO_INICIADO)


def test_error_transicion_invalida():
    import pytest
    with pytest.raises(sm.TransicionInvalidaError):
        raise sm.TransicionInvalidaError(Etapa.ETAPA_3_MDC, Estado.NO_INICIADO, Estado.APLICATIVO_CREADO)


# ---------------------------------------------------------------------------
# Validaciones 9.3
# ---------------------------------------------------------------------------
def test_corrientes_desde_in_eq():
    c = corrientes_desde_in_eq(1.0, k=1.5)
    assert c.icc_3f == 1.5
    assert c.icc_1f == 1.5
    assert c.icc_ee == 1.0
    assert c.icc_2f == round(0.866 * 1.5, 4)
    assert abs(c.icc_pk - round(2 ** 0.5 * 1.5, 4)) < 1e-9


def test_validar_93_coherente_es_valido():
    c = corrientes_desde_in_eq(1.0)
    # Icc_1F real (monofasica) es <= Icc_2F; la derivacion pone Icc_1F=Icc_3F solo como
    # simplificacion, no como entrada valida para la regla Icc_2F >= Icc_1F.
    e = Entradas93(
        icc_subtrans_pico_kap=c.icc_pk, icc_subtrans_3f_ka=c.icc_3f,
        icc_subtrans_2f_ka=c.icc_2f, icc_subtrans_1f_ka=1.0,
        icc_estado_estable_ka=c.icc_ee, in_eq_ka=1.0,
        voltaje_max_kv=15.0, voltaje_nominal_kv=13.8, voltaje_min_kv=12.0,
    )
    informe = validar_93(e)
    assert informe["valido"] is True
    assert all(r["severidad"] != "ERROR" for r in informe["resultados"])


def test_validar_93_detecta_orden_invalido():
    e = Entradas93(icc_subtrans_pico_kap=1.0, icc_subtrans_3f_ka=2.0)  # pk < i3 -> ERROR
    informe = validar_93(e)
    assert informe["valido"] is False
    assert any(r["regla"] == "Icc_pk > Icc_3F" and r["severidad"] == "ERROR" for r in informe["resultados"])


def test_validar_93_marca_pendiente_sin_datos():
    informe = validar_93(Entradas93())
    assert informe["valido"] is True  # sin ERROR
    assert any(r["severidad"] == "PENDIENTE" for r in informe["resultados"])


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
def test_dias_habiles_entre():
    # lun 5 -> vie 9 de enero 2026 = 4 dias habiles (mar,mie,jue,vie)
    assert al.dias_habiles_entre(date(2026, 1, 5), date(2026, 1, 9)) == 4
    assert al.dias_habiles_entre(date(2026, 1, 9), date(2026, 1, 5)) == 0


def test_alertas_vigencia_umbrales():
    hoy = date(2026, 6, 1)
    p = al.ProyectoSnapshot(id=1, nombre_comercial="X", vigencia_conexion=date(2026, 6, 21))  # +20d
    out = al.alertas_vigencia(p, hoy)
    assert {a.dedupe_key for a in out} == {"1:VENCIMIENTO_VIGENCIA:60", "1:VENCIMIENTO_VIGENCIA:30"}


def test_alertas_vigencia_vencida():
    hoy = date(2026, 6, 1)
    p = al.ProyectoSnapshot(id=1, nombre_comercial="X", vigencia_conexion=date(2026, 5, 27))
    out = al.alertas_vigencia(p, hoy)
    assert len(out) == 1 and out[0].dedupe_key == "1:VENCIMIENTO_VIGENCIA:VENCIDO"


def test_alertas_vigencia_lejana_no_dispara():
    hoy = date(2026, 6, 1)
    p = al.ProyectoSnapshot(id=1, nombre_comercial="X", vigencia_conexion=date(2026, 12, 1))
    assert al.alertas_vigencia(p, hoy) == []


def test_alertas_equipos_frontera():
    hoy = date(2026, 6, 1)
    p = al.ProyectoSnapshot(id=1, nombre_comercial="X", fecha_conexion_estimada=date(2026, 7, 1), equipos_solicitados=False)
    assert len(al.alertas_equipos_frontera(p, hoy)) == 1
    p2 = al.ProyectoSnapshot(id=1, nombre_comercial="X", fecha_conexion_estimada=date(2026, 7, 1), equipos_solicitados=True)
    assert al.alertas_equipos_frontera(p2, hoy) == []
    p3 = al.ProyectoSnapshot(id=1, nombre_comercial="X", fecha_conexion_estimada=date(2026, 12, 1), equipos_solicitados=False)
    assert al.alertas_equipos_frontera(p3, hoy) == []


def test_alertas_medidor_or():
    hoy = date(2026, 1, 5)  # lunes
    visita = date(2026, 1, 20)
    p = al.ProyectoSnapshot(
        id=1, nombre_comercial="X", exporta=True, comercializador_es_or=True,
        fecha_visita_protecciones=visita,
        equipos=[al.EquipoSnapshot(tipo="MEDIDOR_PRINCIPAL")],
    )
    assert len(al.alertas_medidor_or(p, hoy)) == 1
    # con medidor ya enviado al OR -> sin alerta
    p2 = al.ProyectoSnapshot(
        id=1, nombre_comercial="X", exporta=True, comercializador_es_or=True,
        fecha_visita_protecciones=visita,
        equipos=[al.EquipoSnapshot(tipo="MEDIDOR_PRINCIPAL", fecha_envio_or=date(2026, 1, 2))],
    )
    assert al.alertas_medidor_or(p2, hoy) == []


def test_alertas_etapa_estancada():
    hoy = date(2026, 2, 2)
    p = al.ProyectoSnapshot(
        id=1, nombre_comercial="X",
        etapas=[al.EtapaSnapshot(etapa=Etapa.ETAPA_2_CARTAS_9_1_9_7, estado_actual=Estado.SOLICITUD_ENVIADA_OR, fecha_estado=date(2026, 1, 1))],
    )
    out = al.alertas_etapa_estancada(p, hoy)
    assert len(out) == 1 and out[0].tipo == al.TipoAlerta.ETAPA_ESTANCADA


def test_alertas_calibracion():
    hoy = date(2026, 6, 1)
    p = al.ProyectoSnapshot(
        id=1, nombre_comercial="X",
        equipos=[al.EquipoSnapshot(tipo="TC", serial="A1", fecha_vencimiento_calibracion=date(2026, 6, 11))],
    )
    assert len(al.alertas_calibracion(p, hoy)) == 1
    p2 = al.ProyectoSnapshot(
        id=1, nombre_comercial="X",
        equipos=[al.EquipoSnapshot(tipo="TC", serial="A1", fecha_vencimiento_calibracion=date(2026, 12, 1))],
    )
    assert al.alertas_calibracion(p2, hoy) == []
