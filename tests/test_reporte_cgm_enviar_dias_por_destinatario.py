"""enviar_reporte_cgm() (app/api/v1/reporte_cgm.py) -- solo pedir a Quoia
los días que cada destinatario realmente necesita.

Antes, en cuanto la request era de un solo día (es_dia_unico), TODOS los
frt_codes de la request se pedían para el mes completo (dias_mes) -- aunque
un Operador de Red normal (no fin de mes) solo usa filas_dia (un día). Un
Cliente sí necesita mes-a-la-fecha siempre (hoja "Diario acumulado"); un
Operador solo el último día del mes (Excel consolidado adicional). Ver
auditoría CGM 2026-08-26, finding #3."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.operadores_red import OperadorRed, OperadorRedContacto
from app.models.clientes import Cliente
from app.models.proyectos import Proyecto
import app.api.v1.reporte_cgm as rc_api
from app.schemas.reporte_cgm import EnviarReporteCGMRequest, DestinatarioSeleccionado


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Frontera.__table__, OperadorRed.__table__, OperadorRedContacto.__table__, Cliente.__table__,
        Proyecto.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _stub_comunes(monkeypatch, llamadas: list):
    monkeypatch.setattr(rc_api, "GaiaClient", lambda: object())
    monkeypatch.setattr(rc_api.svc, "resolver_borders",
                         lambda gaia, codes: {c.lower(): {"id": 1, "category": 1, "name": "X"} for c in codes})

    def _fake_fetch_filas_rango(gaia, frt_code, meta, dias_str):
        filas = []
        for dia in dias_str:
            llamadas.append((frt_code, dia))
            fila = {
                "report date": dia, "border frtcode": frt_code, "border sic code": "X",
                "border category": "cat", "meter": "main", "state": "Exitoso",
                "total reported energy": 0.0,
            }
            fila.update({f"hour {h}": 0.0 for h in range(24)})
            filas.append(fila)
        return filas

    monkeypatch.setattr(rc_api.svc, "fetch_filas_rango", _fake_fetch_filas_rango)
    monkeypatch.setattr(rc_api.svc, "generar_excel", lambda filas, **kw: b"xlsx")
    monkeypatch.setattr(rc_api.svc, "generar_excel_cliente", lambda *a, **kw: b"xlsx")
    monkeypatch.setattr(rc_api.svc, "calcular_resumen_diario", lambda gaia, proyectos, filas_por_frt, dia: [])
    monkeypatch.setattr(rc_api.svc, "calcular_resumen_mensual", lambda gaia, proyectos, filas_por_frt, dias, titulo: [])
    monkeypatch.setattr(rc_api.curvas_energia, "construir_mapa_borders", lambda gaia: {})
    monkeypatch.setattr(rc_api.email_service, "send_reporte_cgm_email", lambda **kw: None)


def test_operador_dia_normal_solo_pide_el_dia_pedido(db, monkeypatch):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion,
                      codigo_frontera="frt001", operador_red_id=10)
    db.add(front)
    db.add(OperadorRed(id=10, nombre_legal="Test Operador"))
    db.add(OperadorRedContacto(id=1, operador_red_id=10, email="op@test.com"))
    db.commit()

    llamadas = []
    _stub_comunes(monkeypatch, llamadas)

    # 2026-08-15 no es fin de mes -- un Operador normal solo debe pedir ese día.
    body = EnviarReporteCGMRequest(
        fecha_inicio=date(2026, 8, 15), fecha_fin=date(2026, 8, 15),
        destinatarios=[DestinatarioSeleccionado(tipo="operador", id=10, proyectos=None)],
    )
    resp = rc_api.enviar_reporte_cgm(body, db=db, _=None)

    assert [dia for _, dia in llamadas] == ["2026-08-15"]
    assert resp.resultados[0].ok is True


def test_operador_fin_de_mes_pide_el_mes_completo(db, monkeypatch):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion,
                      codigo_frontera="frt001", operador_red_id=10)
    db.add(front)
    db.add(OperadorRed(id=10, nombre_legal="Test Operador"))
    db.add(OperadorRedContacto(id=1, operador_red_id=10, email="op@test.com"))
    db.commit()

    llamadas = []
    _stub_comunes(monkeypatch, llamadas)

    body = EnviarReporteCGMRequest(
        fecha_inicio=date(2026, 8, 31), fecha_fin=date(2026, 8, 31),
        destinatarios=[DestinatarioSeleccionado(tipo="operador", id=10, proyectos=None)],
    )
    resp = rc_api.enviar_reporte_cgm(body, db=db, _=None)

    dias_pedidos = sorted(dia for _, dia in llamadas)
    assert dias_pedidos == [f"2026-08-{d:02d}" for d in range(1, 32)]
    assert resp.resultados[0].ok is True


def test_cliente_siempre_pide_el_mes_aunque_no_sea_fin_de_mes(db, monkeypatch):
    front = Frontera(id=2, nombre_frontera="Test2", tipo_frontera=TipoFronteraEnum.generacion,
                      codigo_frontera="frt002", proyecto_id=None)
    db.add(front)
    db.add(Cliente(id=20, razon_social_nombre="Test Cliente"))
    db.commit()

    llamadas = []
    _stub_comunes(monkeypatch, llamadas)
    # cliente_id=157 (CLIENTES_TODAS_LAS_FRONTERAS) evita depender de
    # ProyectoAreaContacto/ProyectoInversionista para resolver sus fronteras.
    monkeypatch.setattr(rc_api, "CLIENTES_TODAS_LAS_FRONTERAS", {20})
    monkeypatch.setattr(rc_api, "get_contactos", lambda db, tipo, cliente_id: ["cliente@test.com"])

    body = EnviarReporteCGMRequest(
        fecha_inicio=date(2026, 8, 15), fecha_fin=date(2026, 8, 15),
        destinatarios=[DestinatarioSeleccionado(tipo="cliente", id=20, proyectos=None)],
    )
    resp = rc_api.enviar_reporte_cgm(body, db=db, _=None)

    dias_pedidos = sorted(dia for _, dia in llamadas)
    assert dias_pedidos == [f"2026-08-{d:02d}" for d in range(1, 16)]  # mes a la fecha
    assert resp.resultados[0].ok is True


def test_operador_y_cliente_con_fronteras_distintas_no_se_mezclan(db, monkeypatch):
    """Dos destinatarios, cada uno con su propia frontera -- el operador
    (no fin de mes) no debe heredar el mes completo que sí necesita el
    cliente."""
    front_op = Frontera(id=1, nombre_frontera="Op", tipo_frontera=TipoFronteraEnum.generacion,
                         codigo_frontera="frtop", operador_red_id=10)
    front_cli = Frontera(id=2, nombre_frontera="Cli", tipo_frontera=TipoFronteraEnum.generacion,
                          codigo_frontera="frtcli", proyecto_id=100)
    db.add_all([front_op, front_cli])
    db.add(OperadorRed(id=10, nombre_legal="Test Operador"))
    db.add(OperadorRedContacto(id=1, operador_red_id=10, email="op@test.com"))
    db.add(Cliente(id=20, razon_social_nombre="Test Cliente"))
    db.commit()

    llamadas = []
    _stub_comunes(monkeypatch, llamadas)
    # Resolución normal por proyecto vinculado (no CLIENTES_TODAS_LAS_FRONTERAS,
    # que traería también la frontera del operador) -- solo frtcli (proyecto 100).
    monkeypatch.setattr(rc_api, "get_proyecto_ids_por_contacto_cliente", lambda db, tipo, cliente_id: [100])
    monkeypatch.setattr(rc_api, "get_contactos", lambda db, tipo, cliente_id: ["cliente@test.com"])

    body = EnviarReporteCGMRequest(
        fecha_inicio=date(2026, 8, 15), fecha_fin=date(2026, 8, 15),
        destinatarios=[
            DestinatarioSeleccionado(tipo="operador", id=10, proyectos=None),
            DestinatarioSeleccionado(tipo="cliente", id=20, proyectos=None),
        ],
    )
    rc_api.enviar_reporte_cgm(body, db=db, _=None)

    dias_frtop = sorted(dia for frt, dia in llamadas if frt == "frtop")
    dias_frtcli = sorted(dia for frt, dia in llamadas if frt == "frtcli")
    assert dias_frtop == ["2026-08-15"]
    assert dias_frtcli == [f"2026-08-{d:02d}" for d in range(1, 16)]
