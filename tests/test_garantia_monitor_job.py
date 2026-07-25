"""Job de monitoreo de cobertura: orquestación (con fakes, sin DB real).

Verifica que, al correr `verificar_cobertura_de_garantias`, por cada garantía
activa se persista un `GarantiaCoberturaHistorico` y que las alertas
AMARILLO/ROJO disparen notificaciones (sin AMARILLO/ROJO no notifica).
"""
import asyncio
from unittest import mock

from app.models.garantias import Garantia
from app.models.garantia_cobertura import GarantiaCoberturaHistorico
from app.models.notificaciones import Notificacion
import app.jobs.garantia_monitor_job as job


class _FakeQuery:
    def __init__(self, resultados):
        self._resultados = resultados

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._resultados[0] if self._resultados else None

    def all(self):
        return self._resultados


class _FakeSession:
    """Sesión falsa: registra los objetos añadidos y despacha query() por modelo."""
    def __init__(self, garantias, usuarios):
        self._por_modelo = {Garantia: garantias, type(None): []}
        self._usuarios = usuarios
        self.added = []
        self.commits = 0
        self.closed = False

    def query(self, modelo):
        from app.models.usuarios import Usuario
        if modelo is Garantia:
            return _FakeQuery(self._por_modelo[Garantia])
        if modelo is Usuario:
            return _FakeQuery(self._usuarios)
        return _FakeQuery([])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _garantia(gid=1, proyecto=None):
    g = mock.Mock(spec=Garantia)
    g.id = gid
    g.proyecto = proyecto
    return g


def _usuario(uid=1, email="ops@unergy.io"):
    u = mock.Mock()
    u.id = uid
    u.email = email
    return u


def _correr(session, resultado):
    """Corre el job con calcular_cobertura_garantia y email parcheados."""
    async def _fake_calc(db, garantia):
        return resultado

    with mock.patch.object(job, "SessionLocal", return_value=session), \
         mock.patch.object(job, "calcular_cobertura_garantia", _fake_calc), \
         mock.patch("app.services.email_service.send_alarm_notification_email") as m_mail:
        resumen = asyncio.run(job.verificar_cobertura_de_garantias())
    return resumen, m_mail


_RES_VERDE = {
    "valor_requerido": 3_000_000.0,
    "valor_actual_garantia": 3_500_000.0,
    "cobertura_porcentaje": 1.17,
    "nivel_alerta": "VERDE",
    "detalles_calculo": {"generacion_kwh_30d": 100_000},
}
_RES_ROJO = {
    "valor_requerido": 3_000_000.0,
    "valor_actual_garantia": 2_400_000.0,
    "cobertura_porcentaje": 0.80,
    "nivel_alerta": "ROJO",
    "detalles_calculo": {"generacion_kwh_30d": 100_000},
}


def test_crea_historico_por_garantia_activa():
    session = _FakeSession(garantias=[_garantia(1)], usuarios=[_usuario()])
    resumen, m_mail = _correr(session, _RES_VERDE)

    historicos = [o for o in session.added if isinstance(o, GarantiaCoberturaHistorico)]
    assert len(historicos) == 1
    assert historicos[0].garantia_id == 1
    assert historicos[0].nivel_alerta == "VERDE"
    assert resumen == {"procesadas": 1, "alertas": 0, "errores": 0}
    # VERDE no notifica
    assert not any(isinstance(o, Notificacion) for o in session.added)
    m_mail.assert_not_called()
    assert session.closed is True


def test_alerta_roja_notifica_a_usuarios():
    session = _FakeSession(garantias=[_garantia(7)], usuarios=[_usuario(1), _usuario(2)])
    resumen, m_mail = _correr(session, _RES_ROJO)

    historicos = [o for o in session.added if isinstance(o, GarantiaCoberturaHistorico)]
    notifs = [o for o in session.added if isinstance(o, Notificacion)]
    assert len(historicos) == 1
    assert historicos[0].nivel_alerta == "ROJO"
    # una notificación in-app por cada usuario de rol operativo
    assert len(notifs) == 2
    assert resumen == {"procesadas": 1, "alertas": 1, "errores": 0}
    m_mail.assert_called_once()
    # anti-fabricación: la alerta debe divulgar que la cifra es provisional
    for n in notifs:
        assert "estimación provisional" in n.mensaje
        assert "requerido estimado" in n.mensaje


def test_cobertura_extrema_se_persiste_sin_overflow():
    # Proyecto con generación 30d casi nula: requerido minúsculo → cobertura enorme.
    # Con NUMERIC(7,4) esto desbordaba cada noche y el error quedaba invisible.
    res = {
        "valor_requerido": 16_000.0,
        "valor_actual_garantia": 100_000_000.0,
        "cobertura_porcentaje": 6250.0,
        "nivel_alerta": "VERDE",
        "detalles_calculo": {"generacion_kwh_30d": 500},
    }
    session = _FakeSession(garantias=[_garantia(3)], usuarios=[_usuario()])
    resumen, _ = _correr(session, res)

    historicos = [o for o in session.added if isinstance(o, GarantiaCoberturaHistorico)]
    assert len(historicos) == 1
    assert historicos[0].cobertura_porcentaje == 6250.0
    assert resumen == {"procesadas": 1, "alertas": 0, "errores": 0}


def test_sin_exposicion_persiste_null_no_cero():
    # Sin exposición (cobertura None → VERDE) el histórico guarda NULL, no un
    # 0.0000+VERDE contradictorio que una UI leería como "0% cubierta, verde".
    res = {
        "valor_requerido": 0.0,
        "valor_actual_garantia": 3_500_000.0,
        "cobertura_porcentaje": None,
        "nivel_alerta": "VERDE",
        "detalles_calculo": {"generacion_kwh_30d": 0},
    }
    session = _FakeSession(garantias=[_garantia(4)], usuarios=[_usuario()])
    resumen, _ = _correr(session, res)

    historicos = [o for o in session.added if isinstance(o, GarantiaCoberturaHistorico)]
    assert len(historicos) == 1
    assert historicos[0].cobertura_porcentaje is None
    assert resumen == {"procesadas": 1, "alertas": 0, "errores": 0}
