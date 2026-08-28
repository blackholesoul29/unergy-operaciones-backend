"""Tests del rediseño de Clientes: campos nuevos, agregados y endpoints panel."""
import datetime as dt

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.contratos import ContratoServicio, PPAContrato, ppa_contrato_proyectos_table
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.services import clientes_panel as cp


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


HOY = dt.date(2026, 7, 9)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Cliente.__table__, Contacto.__table__,
            ClienteDocumentoComercial.__table__,
            Proyecto.__table__, ProyectoInversionista.__table__,
            ContratoServicio.__table__, PPAContrato.__table__,
            ppa_contrato_proyectos_table,
        ],
    )
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _seed_contrato_sin_id_directo(db):
    """Caso real de producción (auditoría 2026-08-27): contratante_id/
    prestador_id casi nunca se pueblan (el campo del wizard es texto libre).
    Cliente 3 es inversionista de Planta Cuarenta, y esa planta tiene un
    contrato de representación SIN contratante_id ni prestador_id -- debe
    seguir viéndose vía el fallback por planta (proyecto_id)."""
    db.add_all([
        Cliente(id=3, razon_social_nombre="Gamma"),
        Proyecto(id=40, nombre_comercial="Planta Cuarenta"),
    ])
    db.flush()
    db.add_all([
        ProyectoInversionista(id=2, proyecto_id=40, cliente_id=3,
                              porcentaje_participacion=100,
                              fecha_inicio=dt.date(2025, 1, 1)),
        ContratoServicio(id=2, proyecto_id=40, contratante_id=None, prestador_id=None,
                         servicio_aplica="representacion", estado="vigente",
                         fecha_fin=dt.date(2026, 8, 1)),
    ])
    db.commit()


def _seed_basico(db):
    """Cliente 1 con: inversión en proyecto 10, contrato de servicio sobre
    proyecto 20, PPA que cubre proyecto 30, y un contacto comercial.
    Cliente 2 sin nada."""
    db.add_all([
        Cliente(id=1, razon_social_nombre="ACME"),
        Cliente(id=2, razon_social_nombre="Beta"),
        Proyecto(id=10, nombre_comercial="Planta Diez"),
        Proyecto(id=20, nombre_comercial="Planta Veinte"),
        Proyecto(id=30, nombre_comercial="Planta Treinta"),
    ])
    db.flush()
    db.add_all([
        ProyectoInversionista(id=1, proyecto_id=10, cliente_id=1,
                              porcentaje_participacion=60,
                              fecha_inicio=dt.date(2025, 1, 1)),
        ContratoServicio(id=1, proyecto_id=20, contratante_id=1,
                         servicio_aplica="cgm", estado="vigente",
                         fecha_fin=dt.date(2026, 8, 1), tarifa_cgm=12.5,
                         indice_indexacion="IPC", renovacion_automatica=True),
        PPAContrato(id=1, comprador_id=1, fecha_fin=dt.date(2028, 1, 1)),
        Contacto(id=1, cliente_id=1, tipo="comercial",
                 nombre="Ana Pérez", email="ana@acme.co", telefono="3001234567"),
    ])
    db.flush()
    db.execute(ppa_contrato_proyectos_table.insert().values(contrato_id=1, proyecto_id=30))
    db.commit()


# ── Campos nuevos en modelos ─────────────────────────────────────────────────

def test_campos_nuevos_en_modelos(db):
    db.add(Contacto(id=9, cliente_id=1, tipo="contable",
                    nombre="Con Table", email="cont@acme.co", telefono="123"))
    db.add(Cliente(id=1, razon_social_nombre="ACME S.A.S."))
    db.flush()
    assert db.query(Contacto).first().telefono == "123"

    cs = ContratoServicio(servicio_aplica="representacion",
                          renovacion_automatica=True,
                          fecha_indexacion=dt.date(2026, 1, 1))
    db.add(cs)
    ppa = PPAContrato(renovacion_automatica=False)
    db.add(ppa)
    db.commit()
    assert db.query(ContratoServicio).first().renovacion_automatica is True
    assert db.query(ContratoServicio).first().fecha_indexacion == dt.date(2026, 1, 1)
    assert db.query(PPAContrato).first().renovacion_automatica is False


# ── Helpers puros ────────────────────────────────────────────────────────────

def test_semaforo_contrato():
    assert cp.semaforo_contrato(None, HOY) == "vigente"                      # indefinido
    assert cp.semaforo_contrato(dt.date(2027, 12, 31), HOY) == "vigente"
    assert cp.semaforo_contrato(dt.date(2026, 8, 1), HOY) == "por_vencer"    # 23 días
    assert cp.semaforo_contrato(dt.date(2026, 10, 7), HOY) == "por_vencer"   # 90 días exactos
    assert cp.semaforo_contrato(dt.date(2026, 10, 8), HOY) == "vigente"      # 91 días
    assert cp.semaforo_contrato(dt.date(2026, 7, 8), HOY) == "vencido"


def test_peor_semaforo_y_renovacion():
    assert cp.peor_semaforo([]) is None
    assert cp.peor_semaforo(["vigente", "por_vencer"]) == "por_vencer"
    assert cp.peor_semaforo(["por_vencer", "vencido", "vigente"]) == "vencido"
    assert cp.renovacion_combinada([]) is None
    assert cp.renovacion_combinada([None, None]) is None
    assert cp.renovacion_combinada([None, False]) is False
    assert cp.renovacion_combinada([False, True]) is True


def test_proyectos_por_cliente(db):
    _seed_basico(db)
    res = cp.proyectos_por_cliente(db, {1, 2})
    assert res[1] == {10, 20, 30}
    assert res.get(2, set()) == set()


def test_servicios_por_cliente(db):
    _seed_basico(db)
    res = cp.servicios_por_cliente(db, {1, 2})
    assert res[1] == {"cgm", "ppa"}
    assert res.get(2, set()) == set()


def test_contacto_comercial_por_cliente(db):
    _seed_basico(db)
    res = cp.contacto_comercial_por_cliente(db, {1, 2})
    assert res[1] == {"nombre": "Ana Pérez", "telefono": "3001234567",
                      "correo": "ana@acme.co", "adicionales": 0}
    assert 2 not in res


def test_alerta_contratos_por_cliente(db):
    _seed_basico(db)
    res = cp.alerta_contratos_por_cliente(db, {1, 2}, HOY)
    assert res[1]["alerta"] == "por_vencer"
    assert res[1]["proximo_vencimiento"] == dt.date(2026, 8, 1)
    assert res.get(2, {"alerta": None})["alerta"] is None


# ── Endpoint vista-comercial ─────────────────────────────────────────────────

def test_vista_comercial(db):
    from app.api.v1 import clientes as clientes_api
    _seed_basico(db)

    filas = clientes_api.vista_comercial(db=db, _=None, hoy=HOY)
    por_id = {f["id"]: f for f in filas}
    acme = por_id[1]
    assert acme["num_plantas"] == 3
    assert set(acme["servicios"]) == {"cgm", "ppa"}
    assert acme["alerta_contrato"] == "por_vencer"
    assert acme["proximo_vencimiento"] == "2026-08-01"
    assert acme["contacto_comercial_nombre"] == "Ana Pérez"
    assert acme["contacto_comercial_telefono"] == "3001234567"
    assert acme["contacto_comercial_correo"] == "ana@acme.co"
    beta = por_id[2]
    assert beta["num_plantas"] == 0
    assert beta["servicios"] == []
    assert beta["alerta_contrato"] is None
    assert beta["contacto_comercial_nombre"] is None


# ── Endpoint panel ───────────────────────────────────────────────────────────

def test_panel_cliente(db):
    from app.api.v1 import clientes as clientes_api
    _seed_basico(db)

    panel = clientes_api.get_cliente_panel(1, db=db, _=None, hoy=HOY)

    assert panel["kpis"]["num_plantas"] == 3
    assert panel["kpis"]["proximo_vencimiento"] == "2026-08-01"
    assert set(panel["kpis"]["servicios"]) == {"cgm", "ppa"}

    plantas = {p["proyecto_id"]: p for p in panel["plantas"]}
    assert plantas[20]["fecha_fin_contrato"] == "2026-08-01"
    assert plantas[20]["renovacion_automatica"] is True
    assert plantas[20]["semaforo"] == "por_vencer"
    assert plantas[10]["participacion_actual"] == 60.0
    assert plantas[10]["fecha_fin_contrato"] is None      # sin contrato directo
    assert plantas[30]["servicios"] == ["ppa"]

    assert len(panel["participaciones_historico"]) == 1
    hist = panel["participaciones_historico"][0]
    assert hist["proyecto_nombre"] == "Planta Diez" and hist["porcentaje"] == 60.0

    cond = {c["contrato_id"]: c for c in panel["condiciones"]}
    assert cond[1]["tarifa_cgm"] == 12.5 and cond[1]["indice_indexacion"] == "IPC"

    tipos = {(c["fuente"], c["semaforo"]) for c in panel["contratos"]}
    assert ("servicio", "por_vencer") in tipos
    assert ("ppa", "vigente") in tipos


def test_panel_cliente_404(db):
    from fastapi import HTTPException
    from app.api.v1 import clientes as clientes_api
    with pytest.raises(HTTPException):
        clientes_api.get_cliente_panel(999, db=db, _=None, hoy=HOY)


# ── Fallback por planta cuando contratante_id/prestador_id no se pueblan ────
# Auditoría de Clientes 2026-08-27: en producción, 0/162 contratos_servicio
# tienen contratante_id o prestador_id (el campo del wizard es texto libre).
# Sin este fallback, "condiciones económicas" del panel 360 siempre estaba
# vacío, y la columna Servicios / alerta de vencimiento de /clientes
# ignoraban en silencio los contratos de servicio reales.

def test_servicios_por_cliente_via_planta_sin_contratante_id(db):
    _seed_contrato_sin_id_directo(db)
    res = cp.servicios_por_cliente(db, {3})
    assert res[3] == {"representacion"}


def test_alerta_contratos_por_cliente_via_planta_sin_contratante_id(db):
    _seed_contrato_sin_id_directo(db)
    res = cp.alerta_contratos_por_cliente(db, {3}, HOY)
    assert res[3]["alerta"] == "por_vencer"
    assert res[3]["proximo_vencimiento"] == dt.date(2026, 8, 1)


def test_vista_comercial_via_planta_sin_contratante_id(db):
    from app.api.v1 import clientes as clientes_api
    _seed_contrato_sin_id_directo(db)

    filas = clientes_api.vista_comercial(db=db, _=None, hoy=HOY)
    gamma = {f["id"]: f for f in filas}[3]
    assert gamma["servicios"] == ["representacion"]
    assert gamma["alerta_contrato"] == "por_vencer"


def test_panel_cliente_condiciones_via_planta_sin_contratante_id(db):
    from app.api.v1 import clientes as clientes_api
    _seed_contrato_sin_id_directo(db)

    panel = clientes_api.get_cliente_panel(3, db=db, _=None, hoy=HOY)

    assert len(panel["condiciones"]) == 1
    assert panel["condiciones"][0]["contrato_id"] == 2
    assert panel["condiciones"][0]["servicio"] == "representacion"
    assert set(panel["kpis"]["servicios"]) == {"representacion"}


def test_servicios_contratos_endpoint_via_planta_sin_contratante_id(db):
    from app.api.v1 import clientes as clientes_api
    _seed_contrato_sin_id_directo(db)

    grupos = clientes_api.list_client_servicios_contratos(3, db=db, _=None, hoy=HOY)
    assert len(grupos) == 1
    assert grupos[0]["servicio"] == "representacion"
    assert grupos[0]["num_plantas"] == 1
