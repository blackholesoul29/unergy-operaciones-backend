"""Tests de AuditMonitorService — creación de alertas y notificación.

Usa una sesión de BD falsa (routing por texto de SQL) para no depender de
Postgres, y un notificador mock para verificar el payload despachado.
"""
from datetime import datetime, timezone

import pytz

from app.services.audit import AuditMonitorService

_BOGOTA = pytz.timezone("America/Bogota")


class _FakeResult:
    def __init__(self, scalar=None, first=None):
        self._scalar = scalar
        self._first = first

    def scalar(self):
        return self._scalar

    def first(self):
        return self._first


class _FakeSession:
    """Sesión mínima: enruta db.execute según el SQL y acumula los add()."""

    def __init__(self, rol="monitoreo"):
        self.rol = rol
        self.added = []
        self._fingerprints = set()
        self.commits = 0

    def execute(self, clause, params=None):
        sql = str(clause)
        if "FROM usuarios" in sql:
            return _FakeResult(scalar=self.rol)
        if "audit_rules" in sql:
            return _FakeResult(first=None)  # sin reglas dinámicas
        if "audit_alerts WHERE fingerprint" in sql:
            fp = (params or {}).get("fp")
            return _FakeResult(scalar=1 if fp in self._fingerprints else None)
        return _FakeResult()

    def add(self, obj):
        self.added.append(obj)
        self._fingerprints.add(obj.fingerprint)

    def flush(self):
        # Simula la asignación de id/created_at que hace Postgres.
        for i, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = i
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(timezone.utc)

    def refresh(self, obj):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


class _MockNotifier:
    def __init__(self):
        self.calls = []

    def dispatch(self, alert):
        self.calls.append(alert)
        return {"slack": True, "email": False}


def _record():
    return {
        "id": 42,
        "tabla": "liquidaciones",
        "registro_id": 7,
        "accion": "UPDATE",
        "usuario_id": 99,
        "usuario_nombre": "Juan Test",
        "cambios": {"valor_neto_cop": {"antes": 1_000_000, "despues": 90_000_000}},
        "created_at": _BOGOTA.localize(datetime(2026, 7, 11, 3, 0)),  # sáb 3am
    }


def test_process_crea_alerta_y_notifica():
    notifier = _MockNotifier()
    svc = AuditMonitorService(notifier=notifier)
    db = _FakeSession(rol="monitoreo")

    created = svc.process_audit_log(db, _record())

    # Se dispararon las 3 razones → 3 alertas.
    assert len(created) == 3
    razones = {a.trigger_reason for a in created}
    assert any("crítico" in r for r in razones)

    # Todas 'pending', entidad correcta, notificadas.
    for a in created:
        assert a.status == "pending"
        assert a.entity_type == "liquidacion"
        assert a.entity_id == "7"
        assert a.usuario_nombre == "Juan Test"
        assert a.notificado is True

    # El notificador recibió cada alerta.
    assert len(notifier.calls) == 3
    assert db.commits >= 1


def test_process_deduplica_por_fingerprint():
    notifier = _MockNotifier()
    svc = AuditMonitorService(notifier=notifier)
    db = _FakeSession(rol="monitoreo")

    first = svc.process_audit_log(db, _record())
    assert len(first) == 3

    # Reprocesar el mismo registro no crea alertas nuevas.
    again = svc.process_audit_log(db, _record())
    assert again == []
    assert len(notifier.calls) == 3  # no se volvió a notificar


def test_process_ignora_tablas_fuera_de_alcance():
    svc = AuditMonitorService(notifier=_MockNotifier())
    db = _FakeSession()
    rec = _record()
    rec["tabla"] = "clientes"  # no es liquidacion/ppa/generacion
    assert svc.process_audit_log(db, rec) == []


def test_process_usuario_autorizado_en_horario_no_alerta():
    svc = AuditMonitorService(notifier=_MockNotifier())
    db = _FakeSession(rol="liquidaciones")
    rec = _record()
    rec["cambios"] = {"nota": {"antes": "a", "despues": "b"}}  # sin valor crítico
    rec["created_at"] = _BOGOTA.localize(datetime(2026, 7, 7, 14, 0))  # mar 2pm
    assert svc.process_audit_log(db, rec) == []
