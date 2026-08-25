"""Facturación de un contrato TERMINADO a mitad de mes.

Regresión: el resolvedor de vigencias (gescon_vigencia) ahora marca al contrato
cerrado por una terminación como `vigente=False, saliente_por_relevo=True` — su
ventana recortada SIGUE contando y debe facturarse hasta su fecha de fin. Pero
`_facturacion_periodo` solo se quedaba con lo `vigente`, así que un código
terminado sin sucesor (ej. SIC 89902 / GD San Pelayo, terminado el 23-jul)
perdía su dueño: desaparecía de su factura PPA (Terpel 8) y su energía real del
despacho caía a "sin PPA", valorada a precio de bolsa. Este test fija que la
energía se factura a su PPA.
"""
import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos
from app.models import PPAContrato, PPATarifa, Proyecto, AsicSolicitud
from app.models.contratos import (
    DespachoContratoMensual, IppMensual, FacturaAgrupacion, FacturaOrden,
    FacturaEmitida, PrecioBolsaMensual,
)
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1 import facturacion as fact_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__,
                PPATarifa.__table__, IppMensual.__table__,
                DespachoContratoMensual.__table__, FacturaAgrupacion.__table__,
                FacturaOrden.__table__, FacturaEmitida.__table__,
                PrecioBolsaMensual.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _setup_terpel8(db):
    """SIC 89902 (GD San Pelayo) en Terpel 8, terminado el 23-jul-2026."""
    proy = Proyecto(id=1, nombre_comercial="GD San Pelayo",
                    tipo_proyecto="minigranja", estado="en_operacion")
    ppa = PPAContrato(id=5, nombre_interno="Terpel 8 (Bancolo)",
                      numero_codigo_contrato="UNERGY-T8",
                      periodo_indexacion_base="2025-01",
                      valor_indexacion_base=175.88, tipo_contrato="venta")
    db.add_all([proy, ppa])
    db.flush()
    # registro: activo 1-jun .. cerrado 23-jul (fecha_fin ya estampada)
    db.add(AsicSolicitud(
        id=212, proyecto_id=1, contrato_ppa_id=5, codigo_sic_contrato="89902",
        tipo_solicitud=TipoSolicitudAsicEnum.registro,
        estado_solicitud=EstadoSolicitudAsicEnum.publicado,
        reemplaza_anterior=True, es_duplicado=False,
        fecha_inicio=date(2026, 6, 1), fecha_fin=date(2026, 7, 23)))
    # terminación: cierra el SIC el 23-jul (identidad heredada → proyecto_id NULL)
    db.add(AsicSolicitud(
        id=231, proyecto_id=None, contrato_ppa_id=5, codigo_sic_contrato="89902",
        tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
        estado_solicitud=EstadoSolicitudAsicEnum.publicado,
        reemplaza_anterior=True, es_duplicado=False,
        fecha_inicio=None, fecha_fin=date(2026, 7, 23)))
    # tarifa + IPP + despacho real (energía de los días que operó)
    db.add(PPATarifa(id=1, contrato_id=5, año=2026, mes=7, tarifa=298.8))
    db.add(IppMensual(id=1, año=2026, mes=7, valor=186.35))
    db.add(PrecioBolsaMensual(id=1, año=2026, mes=7, valor=710.2606))
    db.add(DespachoContratoMensual(
        id=1, periodo="2026-07", codigo_sic_contrato="89902", comprador="TPLC",
        tipo="LARGO PLAZO", kwh=126479.07, dias=22,
        fecha_min=date(2026, 7, 1), fecha_max=date(2026, 7, 22)))
    db.commit()


def test_contrato_terminado_mitad_mes_se_factura_a_su_ppa(db):
    _setup_terpel8(db)
    data = fact_api._facturacion_periodo(db, "2026-07")

    linea = next(l for l in data["lineas"] if l["contrato"] == "89902")
    assert linea["estado"] == "ok", (
        "un contrato terminado a mitad de mes debe seguir mapeado a su PPA, "
        f"no caer a '{linea['estado']}'"
    )
    assert linea["ppa"] == "Terpel 8 (Bancolo)"
    # tarifa indexada = round(298.8 * 186.35 / 175.88, 2)
    assert linea["tarifa_indexada"] == 316.59
    assert linea["facturacion"] == round(126479.07 * 316.59, 2)

    facturas = {g["factura"]: g for g in data["por_factura"]}
    assert "Terpel 8 (Bancolo)" in facturas
    t8 = facturas["Terpel 8 (Bancolo)"]
    assert "89902" in t8["contratos_sic"]
    assert t8["kwh"] == pytest.approx(126479.07, abs=0.01)

    # y NO debe existir una factura "sin PPA" (bolsa) con esta energía
    assert not any(g.get("sin_ppa") for g in data["por_factura"]), (
        "la energía del contrato terminado no debe caer a bolsa/sin PPA"
    )
    assert data["resumen"]["sin_ppa"] == 0
