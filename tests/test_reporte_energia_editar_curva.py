"""editar_curva() (PATCH /reporte-energia/fronteras/{id}) -- corrección
manual de la curva final.

Bug reportado 2026-08-20: al usar "Reportar con otra fuente" -> "Medidor
principal (actualizado)", el chart sí mostraba el nuevo valor pero "Detalle
de las fuentes" y el aviso "el medidor muestra un valor distinto en Quoia"
seguían comparando contra `curva_medidor_principal`, que editar_curva()
nunca actualizaba -- quedaban desincronizados de `curva_final` recién
guardado, así que el aviso jamás desaparecía aunque la persona ya hubiera
adoptado el valor actualizado.
"""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.schemas.reporte_energia import EditarCurvaRequest
from app.api.v1 import reporte_energia as re_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Frontera.__table__, ReporteEnergiaGeneracion.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _sin_quoia(monkeypatch):
    """Sin credenciales de Quoia en tests -- se fuerza a que GaiaClient()
    falle rápido para que _construir_detalle caiga directo a su
    `except Exception: pass` en vez de intentar red real (el fix bajo
    prueba no depende de la consulta en vivo)."""
    def _raise(*a, **kw):
        raise RuntimeError("sin credenciales Quoia en tests")
    monkeypatch.setattr(re_api, "GaiaClient", _raise)


def _frontera_y_reporte(db, medidor_usado, curva_medidor_principal, curva_medidor_respaldo, curva_final):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion)
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=5,
        medidor_usado=medidor_usado,
        curva_final=curva_final,
        curva_medidor_principal=curva_medidor_principal,
        curva_medidor_respaldo=curva_medidor_respaldo,
    )
    db.add(rep)
    db.commit()


def test_adoptar_medidor_principal_actualizado_refresca_el_snapshot(db):
    viejo = [100.0] * 24
    nuevo = [50.0] * 24
    _frontera_y_reporte(db, "principal", curva_medidor_principal=viejo, curva_medidor_respaldo=None, curva_final=viejo)

    body = EditarCurvaRequest(curva_final=nuevo, fuente="principal")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_final == nuevo
    assert detalle.curva_medidor_principal == nuevo, (
        "si el snapshot no se actualiza, 'Detalle de las fuentes' sigue mostrando el valor viejo"
    )


def test_adoptar_medidor_respaldo_actualizado_refresca_su_propio_snapshot(db):
    viejo = [20.0] * 24
    nuevo = [35.0] * 24
    _frontera_y_reporte(db, "respaldo", curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=viejo, curva_final=viejo)

    body = EditarCurvaRequest(curva_final=nuevo, fuente="respaldo")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == nuevo
    assert detalle.curva_medidor_principal == [100.0] * 24, "no debe tocar el otro medidor"


def test_fuente_no_medidor_no_toca_los_snapshots(db):
    """'Inversores x FP' e 'Histórico propio' son estimaciones, no una
    lectura del medidor -- no deben pisar curva_medidor_principal/respaldo."""
    viejo_principal = [100.0] * 24
    _frontera_y_reporte(db, "principal", curva_medidor_principal=viejo_principal, curva_medidor_respaldo=None, curva_final=viejo_principal)

    body = EditarCurvaRequest(curva_final=[10.0] * 24, fuente="inversores")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_principal == viejo_principal
    assert detalle.medidor_usado == "inversores"


def test_sin_columna_respaldo_llena_sigue_la_logica_automatica(db):
    """Si la persona no toca la columna de Respaldo (queda None, no una
    lista de 24 nulos), se recalcula con curva_respaldo_a_reportar() --
    mismo comportamiento de siempre."""
    principal_nuevo = [100.0] * 24
    respaldo_cercano = [100.0] * 23 + [101.0]  # +1 kWh de diferencia total
    _frontera_y_reporte(db, "principal", curva_medidor_principal=[999.0] * 24, curva_medidor_respaldo=respaldo_cercano, curva_final=[999.0] * 24)
    rep = db.get(ReporteEnergiaGeneracion, 1)
    rep.medidor_principal_completo = True
    rep.medidor_respaldo_completo = True
    db.commit()

    body = EditarCurvaRequest(curva_final=principal_nuevo, fuente="principal")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.respaldo_reportado_origen == "medidor"
    assert detalle.curva_respaldo_reportada == respaldo_cercano


def test_columna_respaldo_llena_a_mano_manda_tal_cual_como_manual(db):
    """La persona confirma un respaldo a mano en la tabla, aunque esté MUY
    lejos del principal (fuera de la tolerancia de 1.5 kWh que usa la
    detección automática) -- se guarda igual, es una confirmación explícita."""
    principal_nuevo = [100.0] * 24
    respaldo_a_mano = [80.0] * 24  # 480 kWh de diferencia total -- no pasaría el chequeo automático
    _frontera_y_reporte(db, "principal", curva_medidor_principal=[999.0] * 24, curva_medidor_respaldo=[999.0] * 24, curva_final=[999.0] * 24)

    body = EditarCurvaRequest(curva_final=principal_nuevo, fuente="principal", curva_respaldo_final=respaldo_a_mano)
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.respaldo_reportado_origen == "manual"
    assert detalle.curva_respaldo_reportada == respaldo_a_mano


def test_columna_respaldo_con_menos_de_24_valores_se_rechaza(db):
    from fastapi import HTTPException
    _frontera_y_reporte(db, "principal", curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24, curva_final=[100.0] * 24)

    body = EditarCurvaRequest(curva_final=[100.0] * 24, fuente="principal", curva_respaldo_final=[1.0, 2.0, 3.0])
    with pytest.raises(HTTPException) as exc:
        re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)
    assert exc.value.status_code == 422


class _GaiaDummy:
    pass


def test_respaldo_en_vivo_dentro_de_tolerancia_actualiza_snapshot_y_curva(db, monkeypatch):
    """GD La Hormiguita 2026-08-26: ambos medidores recuperados con éxito,
    la persona adopta 'Medidor principal (actualizado)' -- el respaldo en
    vivo coincide dentro de tolerancia, así que se usa como dato real Y se
    adopta como el nuevo snapshot de referencia (el aviso 'el medidor
    cambió' debe desaparecer, ya quedó validado)."""
    monkeypatch.setattr(re_api, "GaiaClient", lambda: _GaiaDummy())
    monkeypatch.setattr(re_api.curvas, "construir_mapa_medidor_nodo", lambda gaia: {})
    monkeypatch.setattr(re_api.curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})
    respaldo_vivo = [100.0] * 23 + [101.0]  # +1 kWh -- dentro de tolerancia del nuevo principal
    monkeypatch.setattr(re_api.curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series([None] * 24, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=6, medidor_usado="ninguno",
        curva_final=[0.0] * 24, curva_medidor_principal=[None] * 24, curva_medidor_respaldo=[None] * 24,
    )
    db.add(rep)
    db.commit()

    nuevo_principal = [100.0] * 24
    body = EditarCurvaRequest(curva_final=nuevo_principal, fuente="principal")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_principal == nuevo_principal
    assert detalle.curva_medidor_respaldo == respaldo_vivo, (
        "paso la tolerancia -- el snapshot debia adoptar el valor en vivo"
    )
    assert detalle.respaldo_reportado_origen == "medidor"
    assert detalle.curva_respaldo_reportada == respaldo_vivo


def test_respaldo_en_vivo_fuera_de_tolerancia_no_toca_snapshot(db, monkeypatch):
    """MGS GD La Hormiguita 2026-08-26 (caso real): la diferencia (1,54
    kWh) queda apenas fuera de la tolerancia de 1,5 -- sigue cayendo a
    estimado, y el snapshot de curva_medidor_respaldo NO se toca, para que
    el aviso 'el medidor cambió' siga visible (la discrepancia sigue sin
    resolver, no corresponde apagarlo silenciosamente)."""
    monkeypatch.setattr(re_api, "GaiaClient", lambda: _GaiaDummy())
    monkeypatch.setattr(re_api.curvas, "construir_mapa_medidor_nodo", lambda gaia: {})
    monkeypatch.setattr(re_api.curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})
    respaldo_vivo = [100.0] * 23 + [102.0]  # +2 kWh -- fuera de tolerancia
    monkeypatch.setattr(re_api.curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series([None] * 24, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    viejo_respaldo = [None] * 24
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=6, medidor_usado="ninguno",
        curva_final=[0.0] * 24, curva_medidor_principal=[None] * 24, curva_medidor_respaldo=viejo_respaldo,
    )
    db.add(rep)
    db.commit()

    nuevo_principal = [100.0] * 24
    body = EditarCurvaRequest(curva_final=nuevo_principal, fuente="principal")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.respaldo_reportado_origen == "estimado"
    assert detalle.curva_medidor_respaldo == viejo_respaldo, (
        "no paso la tolerancia -- el snapshot no debia tocarse, el aviso de cambio debe seguir visible"
    )


def test_adoptar_respaldo_no_refresca_el_snapshot_de_principal(db, monkeypatch):
    """El chequeo de coherencia solo aplica cuando curva_final viene del
    medidor PRINCIPAL -- elegir 'respaldo' como fuente no debe consultar
    ni tocar el snapshot de curva_medidor_principal."""
    monkeypatch.setattr(re_api, "GaiaClient", lambda: (_ for _ in ()).throw(AssertionError("no debia consultar Quoia")))

    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=6, medidor_usado="ninguno",
        curva_final=[0.0] * 24, curva_medidor_principal=[None] * 24, curva_medidor_respaldo=[None] * 24,
    )
    db.add(rep)
    db.commit()

    nuevo_respaldo = [50.0] * 24
    body = EditarCurvaRequest(curva_final=nuevo_respaldo, fuente="respaldo")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == nuevo_respaldo
    assert detalle.curva_medidor_principal == [None] * 24


def test_refresco_en_vivo_del_otro_medidor_falla_silenciosamente(db, monkeypatch):
    """Si Quoia falla al traer el otro medidor, el guardado no se
    interrumpe -- se queda con el snapshot que ya había (best-effort,
    igual que el resto de las curvas de referencia)."""
    monkeypatch.setattr(re_api, "GaiaClient", lambda: (_ for _ in ()).throw(RuntimeError("Quoia caído")))

    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=6, medidor_usado="ninguno",
        curva_final=[0.0] * 24, curva_medidor_principal=[None] * 24, curva_medidor_respaldo=[None] * 24,
    )
    db.add(rep)
    db.commit()

    nuevo_principal = [100.0] * 24
    body = EditarCurvaRequest(curva_final=nuevo_principal, fuente="principal")
    detalle = re_api.editar_curva(frontera_id=1, body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_principal == nuevo_principal
    assert detalle.curva_medidor_respaldo == [None] * 24
