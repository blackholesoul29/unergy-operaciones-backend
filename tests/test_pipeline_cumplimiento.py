"""Tests de las funciones puras del pipeline mensual de cumplimiento.

Cubren la agregación de energía (lecturas de frontera / generación diaria) y el
cálculo de cumplimiento + valores de liquidación, sin tocar la base de datos
(mismo estilo que el resto de la suite: datos simulados con SimpleNamespace).
"""
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.pipeline_cumplimiento import (
    agregar_energia_lecturas_kwh,
    agregar_energia_generacion_kwh,
    calcular_valores_cumplimiento,
)


def _lec(fecha_hora, export):
    return SimpleNamespace(fecha_hora=fecha_hora, energia_activa_export_kwh=export)


def _gen(fecha, kwh):
    return SimpleNamespace(fecha=fecha, kwh_real=kwh)


# ── agregar_energia_lecturas_kwh ─────────────────────────────────────────────

def test_lecturas_suma_solo_el_mes_e_ignora_none():
    lecturas = [
        _lec(datetime(2026, 6, 5, 10), Decimal("100")),
        _lec(datetime(2026, 6, 20, 10), 50.5),
        _lec(datetime(2026, 6, 25, 10), None),      # None → ignorado (no es 0)
        _lec(datetime(2026, 7, 1, 10), 999),        # otro mes → fuera
        _lec(None, 5),                              # sin fecha → fuera
    ]
    assert agregar_energia_lecturas_kwh(lecturas, 2026, 6) == 150.5


def test_lecturas_sin_dato_devuelve_none():
    lecturas = [_lec(datetime(2026, 7, 1, 10), 10), _lec(datetime(2026, 6, 1, 10), None)]
    assert agregar_energia_lecturas_kwh(lecturas, 2026, 6) is None
    assert agregar_energia_lecturas_kwh([], 2026, 6) is None


# ── agregar_energia_generacion_kwh ───────────────────────────────────────────

def test_generacion_suma_solo_el_mes():
    gens = [
        _gen(date(2026, 6, 1), Decimal("30")),
        _gen(date(2026, 6, 2), 20),
        _gen(date(2026, 5, 31), 1000),   # mes anterior → fuera
        _gen(date(2026, 6, 3), None),    # None → ignorado
    ]
    assert agregar_energia_generacion_kwh(gens, 2026, 6) == 50.0


def test_generacion_sin_dato_devuelve_none():
    assert agregar_energia_generacion_kwh([], 2026, 6) is None
    assert agregar_energia_generacion_kwh([_gen(date(2026, 6, 1), None)], 2026, 6) is None


# ── calcular_valores_cumplimiento ────────────────────────────────────────────

def test_sin_compromisos():
    v = calcular_valores_cumplimiento(gen_kwh=120_000, min_mwh=None, max_mwh=None)
    assert v["estado_calc"] == "sin_compromisos"
    assert v["gen_total_mwh"] == 120.0
    assert v["compras_bolsa_mwh"] is None
    assert v["energia_facturable_kwh"] == 120_000.0


def test_deficit_calcula_compras_y_cop():
    # 80 MWh generados vs mínimo 100 MWh → 20 MWh de compras en bolsa.
    v = calcular_valores_cumplimiento(
        gen_kwh=80_000, min_mwh=100, max_mwh=150,
        tarifa_ppa_cop_kwh=300, precio_bolsa_cop_kwh=250,
    )
    assert v["estado_calc"] == "deficit"
    assert v["compras_bolsa_mwh"] == 20.0
    assert v["excedentes_bolsa_mwh"] == 0.0
    assert v["compras_bolsa_cop"] == 20 * 1000 * 250
    # Valoración = generación (MWh) * 1000 * tarifa (COP/kWh)
    assert v["valoracion_contrato_cop"] == 80 * 1000 * 300
    # Facturable capado al máximo (150 MWh) pero gen < max → toda la generación.
    assert v["energia_facturable_kwh"] == 80_000.0


def test_ok_dentro_del_rango():
    v = calcular_valores_cumplimiento(gen_kwh=120_000, min_mwh=100, max_mwh=150)
    assert v["estado_calc"] == "ok"
    assert v["compras_bolsa_mwh"] == 0.0
    assert v["excedentes_bolsa_mwh"] == 0.0


def test_excedente_sobre_el_maximo_y_facturable_capado():
    v = calcular_valores_cumplimiento(
        gen_kwh=170_000, min_mwh=100, max_mwh=150, precio_bolsa_cop_kwh=200,
    )
    assert v["estado_calc"] == "excedente"
    assert v["excedentes_bolsa_mwh"] == 20.0
    assert v["excedentes_bolsa_cop"] == 20 * 1000 * 200
    # Facturable capado al máximo contratado (150 MWh = 150.000 kWh).
    assert v["energia_facturable_kwh"] == 150_000.0


def test_gen_none_se_trata_como_cero():
    v = calcular_valores_cumplimiento(gen_kwh=None, min_mwh=100, max_mwh=150)
    assert v["gen_total_mwh"] == 0.0
    assert v["estado_calc"] == "deficit"
    assert v["compras_bolsa_mwh"] == 100.0


def test_max_ausente_usa_el_minimo_como_tope():
    # Sin máximo explícito, el tope es el mínimo: 130 > 100 → excedente de 30.
    v = calcular_valores_cumplimiento(gen_kwh=130_000, min_mwh=100, max_mwh=None)
    assert v["estado_calc"] == "excedente"
    assert v["excedentes_bolsa_mwh"] == 30.0


# ── run_pipeline_mensual: sin dato de energía NO sobrescribe el snapshot ──────

def test_pipeline_sin_energia_no_sobreescribe_snapshot(monkeypatch):
    """Regresión: un contrato sin dato de energía en las fuentes locales NO debe
    fabricar un déficit total ni sobrescribir un cumplimiento ya calculado (p.ej.
    por cerrar-periodo, fuente API Unergy) con ceros. Debe omitirse y contarse en
    ``contratos_sin_dato``.

    Ausencia de dato ≠ 0 MWh: antes de este guard, el pipeline mensual
    ``origen='automatico'`` clobbereaba el snapshot cerrado con gen=0 → déficit y
    ``compras_bolsa_cop`` fantasma (corrupción de dato financiero).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.api.v1.cumplimiento as cumpl_api
    import app.services.pipeline_cumplimiento as pipe
    import app.models  # noqa: F401  registra todos los modelos en el metadata
    from app.models.base import Base
    from app.models.cumplimiento import CumplimientoMensual, EstadoCumplimientoEnum
    from app.models.contratos import PPACompromisoEnergia, PPATarifa
    from app.models.liquidaciones import Liquidacion, LiquidacionXMDato

    engine = create_engine("sqlite:///:memory:")
    # Se crean también las tablas de liquidación para que la RUTA de sobrescritura
    # se ejerza de verdad: sin el guard, el orquestador llega hasta el DELETE de
    # liquidacion_xm_datos, así el test falla por la aserción de clobber (y no por
    # una tabla ausente).
    Base.metadata.create_all(
        engine,
        tables=[CumplimientoMensual.__table__, PPACompromisoEnergia.__table__,
                PPATarifa.__table__, Liquidacion.__table__, LiquidacionXMDato.__table__],
    )
    db = sessionmaker(bind=engine)()

    # Snapshot autoritativo previo: energía real 123.0 MWh, estado cerrado.
    prev = CumplimientoMensual(
        id=1, contrato_ppa_id=42, anio=2026, mes=6,
        gen_total_mwh=123.0, compromiso_mwh=100.0,
        estado=EstadoCumplimientoEnum.cerrado, origen="manual",
    )
    db.add(prev)
    db.commit()

    contrato = SimpleNamespace(id=42, numero_codigo_contrato="C-42")
    monkeypatch.setattr(cumpl_api, "_contratos_vigentes", lambda db, a, m: [contrato])
    monkeypatch.setattr(
        cumpl_api, "_resolve_gescon",
        lambda db, cod, a, m: [SimpleNamespace(proyecto_id=7, porcentaje_despacho=1.0)],
    )
    monkeypatch.setattr(cumpl_api, "_get_bolsa_avg", lambda db, a, m: {"precio_promedio": 250.0})
    monkeypatch.setattr(pipe, "_usuario_sistema_id", lambda db: 1)
    # Sin dato de energía en las fuentes locales para la planta.
    monkeypatch.setattr(
        pipe, "_energia_proyecto_kwh",
        lambda db, pid, a, m: {"energia_kwh": None, "fuente": None, "frontera_id": None},
    )

    result = pipe.run_pipeline_mensual(db, 2026, 6)

    assert result["contratos_sin_dato"] == 1
    assert result["codigos_sin_dato"] == ["C-42"]
    assert result["cumplimiento_recs_processed"] == 0
    assert result["liquidaciones_recs_created"] == 0

    db.refresh(prev)
    # El snapshot previo queda INTACTO (no clobbered a 0 / déficit fantasma).
    assert float(prev.gen_total_mwh) == 123.0
    assert prev.estado == EstadoCumplimientoEnum.cerrado
    assert prev.origen == "manual"
    db.close()
