"""resumen_historico() (GET /reporte-energia/resumen-historico)

Patrones a través de varios días, por frontera -- distinto de /resumen
(un solo día). Distribución de fuente agrupada en Medidor/Inversor/
Estimación/Sin fuente (decidido con el usuario 2026-08-21 -- el
vocabulario crudo de medidor_usado/caso es demasiado técnico para un KPI
de negocio), con drill-down por frontera; datos incompletos de medidor/
inversores (solo Generación); intervención manual recurrente; y
éxito/fallo de recuperación activa por medidor (parseado de
recuperacion_datos, texto libre). Cada sección trae además un par de
'callouts' -- métricas de una sola línea para mostrar arriba de su tabla.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.api.v1 import reporte_energia as re_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Frontera.__table__, ReporteEnergiaGeneracion.__table__, ReporteEnergiaConsumo.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _frontera(db, id_, nombre, tipo=TipoFronteraEnum.generacion):
    f = Frontera(id=id_, nombre_frontera=nombre, tipo_frontera=tipo, codigo_frontera=f"frt{id_}")
    db.add(f)
    return f


def _gen(db, id_, frontera_id, fecha, **kw):
    rep = ReporteEnergiaGeneracion(id=id_, frontera_id=frontera_id, fecha=fecha, caso=kw.pop("caso", 1), **kw)
    db.add(rep)
    return rep


def _con(db, id_, frontera_id, fecha, **kw):
    rep = ReporteEnergiaConsumo(id=id_, frontera_id=frontera_id, fecha=fecha, caso=kw.pop("caso", "CGM"), **kw)
    db.add(rep)
    return rep


def test_hasta_antes_de_desde_da_422(db):
    with pytest.raises(HTTPException) as exc:
        re_api.resumen_historico(desde=date(2026, 8, 10), hasta=date(2026, 8, 1), db=db, _=None)
    assert exc.value.status_code == 422


def test_distribucion_de_fuente_agrupa_medidor_inversor_estimacion(db):
    _frontera(db, 1, "Planta A")
    _frontera(db, 2, "Planta B Consumo", tipo=TipoFronteraEnum.consumo_auxiliar)
    _gen(db, 1, 1, date(2026, 8, 1), medidor_usado="cgm")           # Medidor
    _gen(db, 2, 1, date(2026, 8, 2), medidor_usado="principal")     # Medidor
    _gen(db, 3, 1, date(2026, 8, 3), medidor_usado="inversores")    # Inversor
    _gen(db, 4, 1, date(2026, 8, 4), medidor_usado="historico")     # Estimación
    _gen(db, 5, 1, date(2026, 8, 5), medidor_usado="revisar")       # Sin fuente
    _con(db, 1, 2, date(2026, 8, 1), caso="CGM")                    # Medidor
    _con(db, 2, 2, date(2026, 8, 2), caso="Histórico")              # Estimación
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 5), db=db, _=None)
    gen_map = {i.etiqueta: i.total for i in resp.distribucion_fuente_generacion}
    assert gen_map == {"Medidor": 2, "Inversor": 1, "Estimación": 1, "Sin fuente": 1}
    con_map = {i.etiqueta: i.total for i in resp.distribucion_fuente_consumo}
    assert con_map == {"Medidor": 1, "Estimación": 1}


def test_excluida_no_cuenta_como_fuente_pero_si_en_dias_totales(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), medidor_usado="cgm")
    _gen(db, 2, 1, date(2026, 8, 2), caso="Error", medidor_usado="excluida")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 2), db=db, _=None)
    gen_map = {i.etiqueta: i.total for i in resp.distribucion_fuente_generacion}
    assert gen_map == {"Medidor": 1}  # la excluida no aparece como fuente

    detalle = resp.detalle_fuente_generacion
    assert len(detalle) == 1
    assert detalle[0].dias_totales == 2  # pero sí cuenta para el denominador
    assert detalle[0].dias_grupo == 1


def test_detalle_por_frontera_incluye_desglose_de_fuentes_crudas(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), medidor_usado="historico")
    _gen(db, 2, 1, date(2026, 8, 2), medidor_usado="historico")
    _gen(db, 3, 1, date(2026, 8, 3), medidor_usado="relleno_horario")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    assert len(resp.detalle_fuente_generacion) == 1
    item = resp.detalle_fuente_generacion[0]
    assert item.grupo == "Estimación"
    assert item.dias_totales == 3
    assert item.dias_grupo == 3
    desglose = {d.etiqueta: d.dias for d in item.desglose}
    assert desglose == {"Histórico propio": 2, "Relleno horario": 1}


def test_fuera_del_rango_no_cuenta(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 7, 1), medidor_usado="cgm")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 31), db=db, _=None)
    assert resp.distribucion_fuente_generacion == []
    assert resp.detalle_fuente_generacion == []


def test_incompletos_solo_cuenta_los_false_y_da_dias_con_fila(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 2, 1, date(2026, 8, 2), medidor_principal_completo=True, medidor_respaldo_completo=False, solenium_completo=None)
    _gen(db, 3, 1, date(2026, 8, 3), medidor_principal_completo=False, medidor_respaldo_completo=False, solenium_completo=False)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    assert len(resp.incompletos) == 1
    item = resp.incompletos[0]
    assert item.frontera_id == 1
    assert item.veces_medidor_principal_incompleto == 2
    assert item.veces_medidor_respaldo_incompleto == 2
    assert item.veces_solenium_incompleto == 1
    assert item.dias_con_fila == 3

    callouts = {c.etiqueta: c.valor for c in resp.incompletos_callouts}
    assert callouts["fronteras con al menos un día de datos incompletos"] == "1"
    assert callouts["con más del 30% de sus días afectados"] == "1"  # 2/3 = 67%


def test_incompletos_sin_ningun_problema_no_aparece_en_la_tabla(db):
    _frontera(db, 1, "Planta perfecta")
    _gen(db, 1, 1, date(2026, 8, 1), medidor_principal_completo=True, medidor_respaldo_completo=True, solenium_completo=True)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 1), db=db, _=None)
    assert resp.incompletos == []
    callouts = {c.etiqueta: c.valor for c in resp.incompletos_callouts}
    assert callouts["fronteras con al menos un día de datos incompletos"] == "0"


def test_incompletos_se_ordena_de_mas_a_menos_critico(db):
    _frontera(db, 1, "Poco afectada")
    _frontera(db, 2, "Muy afectada")
    # Poco afectada: 1 de 4 dias con medidor principal incompleto (25%)
    _gen(db, 1, 1, date(2026, 8, 1), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 2, 1, date(2026, 8, 2), medidor_principal_completo=True, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 3, 1, date(2026, 8, 3), medidor_principal_completo=True, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 4, 1, date(2026, 8, 4), medidor_principal_completo=True, medidor_respaldo_completo=True, solenium_completo=True)
    # Muy afectada: 4 de 4 dias con medidor principal incompleto (100%)
    _gen(db, 5, 2, date(2026, 8, 1), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 6, 2, date(2026, 8, 2), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 7, 2, date(2026, 8, 3), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 8, 2, date(2026, 8, 4), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 4), db=db, _=None)
    assert [i.frontera_id for i in resp.incompletos] == [2, 1]


def test_intervencion_manual_combina_generacion_y_consumo(db):
    _frontera(db, 1, "Planta A")
    _frontera(db, 2, "Planta A Consumo", tipo=TipoFronteraEnum.consumo_auxiliar)
    _gen(db, 1, 1, date(2026, 8, 1), revisar_manualmente=True, editado_manualmente=False)
    _gen(db, 2, 1, date(2026, 8, 2), revisar_manualmente=True, editado_manualmente=True)
    _con(db, 1, 2, date(2026, 8, 1), revisar_manualmente=False, editado_manualmente=True)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 2), db=db, _=None)
    por_tipo = {i.tipo: i for i in resp.intervencion_manual}
    assert por_tipo["generacion"].veces_revisar_manualmente == 2
    assert por_tipo["generacion"].veces_editado_manualmente == 1
    assert por_tipo["consumo"].veces_revisar_manualmente == 0
    assert por_tipo["consumo"].veces_editado_manualmente == 1

    callouts = {c.etiqueta: c.valor for c in resp.intervencion_manual_callouts}
    assert callouts["fronteras necesitaron revisión manual"] == "1"  # solo generación
    assert callouts["ya corregidas a mano al menos una vez"] == "2"  # generación + consumo


def test_intervencion_manual_sin_ninguna_bandera_no_aparece(db):
    _frontera(db, 1, "Planta perfecta")
    _gen(db, 1, 1, date(2026, 8, 1), revisar_manualmente=False, editado_manualmente=False)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 1), db=db, _=None)
    assert resp.intervencion_manual == []


def test_intervencion_manual_se_ordena_de_mas_a_menos_critico(db):
    _frontera(db, 1, "Poco afectada")
    _frontera(db, 2, "Muy afectada")
    _gen(db, 1, 1, date(2026, 8, 1), revisar_manualmente=True, editado_manualmente=False)
    _gen(db, 2, 1, date(2026, 8, 2), revisar_manualmente=False, editado_manualmente=False)
    _gen(db, 3, 2, date(2026, 8, 1), revisar_manualmente=True, editado_manualmente=False)
    _gen(db, 4, 2, date(2026, 8, 2), revisar_manualmente=True, editado_manualmente=False)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 2), db=db, _=None)
    assert [i.frontera_id for i in resp.intervencion_manual] == [2, 1]


def test_recuperacion_activa_parsea_principal_y_respaldo_por_separado(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), recuperacion_datos="principal: éxito")
    _gen(db, 2, 1, date(2026, 8, 2), recuperacion_datos="principal: falló, respaldo: éxito")
    _gen(db, 3, 1, date(2026, 8, 3), recuperacion_datos=None)  # no cuenta -- sin intento
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    assert len(resp.recuperacion_activa) == 1
    item = resp.recuperacion_activa[0]
    assert item.intentos_principal == 2
    assert item.exitos_principal == 1
    assert item.intentos_respaldo == 1
    assert item.exitos_respaldo == 1

    callouts = {c.etiqueta: c.valor for c in resp.recuperacion_activa_callouts}
    assert callouts["tasa de éxito global de la recuperación activa"] == "67%"  # 2/3
    # respaldo solo tuvo 1 intento -- no alcanza el mínimo de 2 para juzgarlo
    assert callouts["medidores que casi nunca responden"] == "0"


def test_medidor_con_dos_o_mas_intentos_y_baja_tasa_cuenta_como_problema(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), recuperacion_datos="principal: falló")
    _gen(db, 2, 1, date(2026, 8, 2), recuperacion_datos="principal: falló")
    _gen(db, 3, 1, date(2026, 8, 3), recuperacion_datos="principal: éxito")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    callouts = {c.etiqueta: c.valor for c in resp.recuperacion_activa_callouts}
    assert callouts["medidores que casi nunca responden"] == "1"  # 1/3 = 33% < 34%, 3 intentos


def test_recuperacion_activa_se_ordena_de_menor_a_mayor_tasa_de_exito(db):
    _frontera(db, 1, "Casi siempre falla")
    _frontera(db, 2, "Casi siempre funciona")
    _gen(db, 1, 1, date(2026, 8, 1), recuperacion_datos="principal: falló")
    _gen(db, 2, 1, date(2026, 8, 2), recuperacion_datos="principal: falló")
    _gen(db, 3, 2, date(2026, 8, 1), recuperacion_datos="principal: éxito")
    _gen(db, 4, 2, date(2026, 8, 2), recuperacion_datos="principal: éxito")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 2), db=db, _=None)
    assert [i.frontera_id for i in resp.recuperacion_activa] == [1, 2]
