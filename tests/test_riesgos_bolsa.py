"""Tests del módulo Descubrimientos y Gestión de Riesgos de Bolsa.

Cubre:
  * xm_parser: aplanado del formato ancho de XM y conversión kWh→MWh.
  * services (núcleo puro): exposición, indicadores de riesgo, proyección.
  * services (CRUD sobre BD): SQLite en memoria con sólo la tabla precio_bolsa.
"""
from datetime import datetime, date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
from app.models.riesgos_bolsa import PrecioBolsa
from app.models.generacion import GeneracionDiaria
from app.models.contratos import (
    PPAContrato, PPACompromisoEnergia, ppa_contrato_proyectos_table,
)
from app.utils.xm_parser import (
    parse_xm_precio_bolsa, parse_xm_precio_bolsa_bytes, parse_xm_precio_bolsa_df,
    XMPrecioBolsaParseError,
)
from app.services import riesgos_bolsa as svc


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):  # JSONB → TEXT en SQLite
    return "TEXT"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """Sesión SQLite en memoria con sólo la tabla precio_bolsa.

    Se crea con DDL crudo (INTEGER PRIMARY KEY AUTOINCREMENT) porque en SQLite
    un PK BigInteger no se autoincrementa; en Postgres la columna es BIGSERIAL.
    El modelo ORM mapea sin problema contra esta tabla.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE precio_bolsa ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  fecha_hora TIMESTAMP NOT NULL,"
            "  precio_cop_mwh NUMERIC(10,2) NOT NULL,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX ix_precio_bolsa_fecha_hora ON precio_bolsa (fecha_hora)"
        ))
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── xm_parser ───────────────────────────────────────────────────────────────

def _csv_ancho() -> bytes:
    # Fecha + horas 0..2 (recortado); XM publica en COP/kWh.
    return b"Fecha;0;1;2\n2026-07-01;200.5;210;220\n2026-07-02;190;195;200\n"


def test_parse_bytes_convierte_kwh_a_mwh():
    filas = parse_xm_precio_bolsa_bytes(_csv_ancho())
    # 2 días x 3 horas = 6 filas
    assert len(filas) == 6
    primera = filas[0]
    assert primera["fecha_hora"] == datetime(2026, 7, 1, 0)
    # 200.5 COP/kWh -> 200500.00 COP/MWh
    assert primera["precio_cop_mwh"] == Decimal("200500.00")


def test_parse_bytes_sin_conversion_mantiene_valor():
    filas = parse_xm_precio_bolsa_bytes(_csv_ancho(), convertir_kwh_a_mwh=False)
    assert filas[0]["precio_cop_mwh"] == Decimal("200.50")


def test_parse_ordena_por_fecha_hora():
    filas = parse_xm_precio_bolsa_bytes(_csv_ancho())
    fechas = [f["fecha_hora"] for f in filas]
    assert fechas == sorted(fechas)
    assert fechas[-1] == datetime(2026, 7, 2, 2)


def test_parse_columnas_hora_con_texto():
    import pandas as pd
    df = pd.DataFrame({"Fecha": ["2026-07-01"], "Hora 00": [100], "HORA 23": [300]})
    filas = parse_xm_precio_bolsa_df(df)
    horas = sorted(f["fecha_hora"].hour for f in filas)
    assert horas == [0, 23]


def test_parse_omite_precios_nulos():
    import pandas as pd
    df = pd.DataFrame({"Fecha": ["2026-07-01"], "0": [None], "1": [150]})
    filas = parse_xm_precio_bolsa_df(df)
    assert len(filas) == 1
    assert filas[0]["fecha_hora"].hour == 1


def test_parse_sin_columnas_hora_lanza_error():
    import pandas as pd
    df = pd.DataFrame({"Fecha": ["2026-07-01"], "otra": ["x"]})
    with pytest.raises(XMPrecioBolsaParseError):
        parse_xm_precio_bolsa_df(df)


def test_parse_df_vacio_devuelve_lista_vacia():
    import pandas as pd
    assert parse_xm_precio_bolsa_df(pd.DataFrame()) == []


def test_parse_archivo_csv(tmp_path):
    p = tmp_path / "precio.csv"
    p.write_bytes(_csv_ancho())
    filas = parse_xm_precio_bolsa(str(p))
    assert len(filas) == 6


def test_parse_archivo_inexistente():
    with pytest.raises(FileNotFoundError):
        parse_xm_precio_bolsa("/no/existe/precio.csv")


# ── Núcleo puro: exposición ──────────────────────────────────────────────────

def test_compute_exposure_excedente_positivo():
    # gen 100 MWh, obligación 60 MWh, precio 300k -> (40)*300000 = 12,000,000
    assert svc.compute_exposure(100, 60, 300_000) == 12_000_000.0


def test_compute_exposure_deficit_negativo():
    assert svc.compute_exposure(40, 60, 300_000) == -6_000_000.0


def test_compute_exposure_dato_faltante_es_none():
    assert svc.compute_exposure(None, 60, 300_000) is None
    assert svc.compute_exposure(100, None, 300_000) is None
    assert svc.compute_exposure(100, 60, None) is None


# ── Núcleo puro: indicadores de riesgo ───────────────────────────────────────

def test_risk_indicators_basico():
    ind = svc.compute_risk_indicators([100.0, 200.0, 300.0])
    assert ind["n"] == 3
    assert ind["exposicion_total_cop"] == 600.0
    assert ind["exposicion_media_cop"] == 200.0
    assert ind["exposicion_max_cop"] == 300.0
    assert ind["exposicion_min_cop"] == 100.0
    assert ind["exposicion_std_cop"] == 100.0  # stdev muestral de [100,200,300]


def test_risk_indicators_ignora_nones():
    ind = svc.compute_risk_indicators([100.0, None, 300.0])
    assert ind["n"] == 2


def test_risk_indicators_vacio():
    ind = svc.compute_risk_indicators([])
    assert ind["n"] == 0
    assert ind["exposicion_total_cop"] == 0.0
    assert ind["var_95_cop"] is None


def test_risk_indicators_var_es_percentil_5():
    vals = [float(x) for x in range(0, 101)]  # 0..100
    ind = svc.compute_risk_indicators(vals)
    assert ind["var_95_cop"] == 5.0
    assert ind["exposicion_min_cop"] == 0.0


# ── Núcleo puro: proyección de escenarios ─────────────────────────────────────

def test_project_exposure_scenario():
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    res = svc.project_exposure_scenario(
        precio_bolsa_forecast={d1: 300_000, d2: 250_000},
        generacion_forecast={d1: 100, d2: 50},
        ppa_obligations={d1: 60, d2: 60},
    )
    assert len(res["puntos"]) == 2
    assert res["puntos"][0]["exposicion_cop"] == 12_000_000.0   # (100-60)*300k
    assert res["puntos"][1]["exposicion_cop"] == -2_500_000.0   # (50-60)*250k
    assert res["indicadores"]["exposicion_total_cop"] == 9_500_000.0


def test_project_exposure_scenario_gen_faltante_es_cero():
    d1 = date(2026, 7, 1)
    res = svc.project_exposure_scenario(precio_bolsa_forecast={d1: 300_000})
    # gen y obligación ausentes -> 0 -> exposición 0
    assert res["puntos"][0]["exposicion_cop"] == 0.0


# ── CRUD sobre BD ─────────────────────────────────────────────────────────────

def test_create_y_get_by_datetime(db):
    fh = datetime(2026, 7, 1, 10)
    svc.create_precio_bolsa_entry(db, {"fecha_hora": fh, "precio_cop_mwh": Decimal("250000.00")})
    row = svc.get_precio_bolsa_by_datetime(db, fh)
    assert row is not None
    assert row.precio_cop_mwh == Decimal("250000.00")


def test_bulk_upsert_inserta_y_actualiza(db):
    fh1, fh2 = datetime(2026, 7, 1, 0), datetime(2026, 7, 1, 1)
    r1 = svc.bulk_upsert_precio_bolsa(db, [
        {"fecha_hora": fh1, "precio_cop_mwh": Decimal("100.00")},
        {"fecha_hora": fh2, "precio_cop_mwh": Decimal("200.00")},
    ])
    assert r1 == {"insertados": 2, "actualizados": 0, "total_filas": 2}

    r2 = svc.bulk_upsert_precio_bolsa(db, [
        {"fecha_hora": fh1, "precio_cop_mwh": Decimal("999.00")},  # update
        {"fecha_hora": datetime(2026, 7, 1, 2), "precio_cop_mwh": Decimal("300.00")},  # insert
    ])
    assert r2 == {"insertados": 1, "actualizados": 1, "total_filas": 2}
    assert svc.get_precio_bolsa_by_datetime(db, fh1).precio_cop_mwh == Decimal("999.00")


def test_get_range(db):
    for h in range(3):
        svc.create_precio_bolsa_entry(
            db, {"fecha_hora": datetime(2026, 7, 1, h), "precio_cop_mwh": Decimal("100.00")}
        )
    filas = svc.get_precio_bolsa_range(db, datetime(2026, 7, 1, 0), datetime(2026, 7, 1, 1))
    assert len(filas) == 2


def test_precio_promedio_por_dia(db):
    svc.bulk_upsert_precio_bolsa(db, [
        {"fecha_hora": datetime(2026, 7, 1, 0), "precio_cop_mwh": Decimal("100.00")},
        {"fecha_hora": datetime(2026, 7, 1, 1), "precio_cop_mwh": Decimal("300.00")},
        {"fecha_hora": datetime(2026, 7, 2, 0), "precio_cop_mwh": Decimal("500.00")},
    ])
    prom = svc.get_precio_promedio_por_dia(db, date(2026, 7, 1), date(2026, 7, 2))
    assert prom[date(2026, 7, 1)] == 200.0
    assert prom[date(2026, 7, 2)] == 500.0


# ── Pipeline de exposición sobre BD (precio + generación + obligación PPA) ─────

@pytest.fixture
def db_expo():
    """Sesión SQLite con las tablas del pipeline de exposición.

    No se crea `proyectos`/`clientes`: el servicio filtra por `proyecto_id` y
    hace join a `ppa_contrato_proyectos` sin tocar esas tablas, y SQLite no
    fuerza las FKs. Ejercita el código de BD más delicado (join M:N + prorrateo).
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        PrecioBolsa.__table__, GeneracionDiaria.__table__,
        PPAContrato.__table__, PPACompromisoEnergia.__table__,
        ppa_contrato_proyectos_table,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


_expo_id = iter(range(1, 100_000))


def _add_precio_dia(db, dia, precio_mwh):
    db.add(PrecioBolsa(id=next(_expo_id),
                       fecha_hora=datetime(dia.year, dia.month, dia.day, 0),
                       precio_cop_mwh=Decimal(str(precio_mwh))))


def _add_generacion(db, dia, planta_id, mwh):
    db.add(GeneracionDiaria(id=next(_expo_id), proyecto_id=planta_id,
                            fecha=dia, kwh_real=Decimal(str(mwh * 1000)), fuente="manual"))


def _add_contrato_con_compromiso(db, planta_id, anio, mes, energia_minima_mwh):
    cid = next(_expo_id)
    db.add(PPAContrato(id=cid))  # deleted_at None → vigente
    db.flush()
    db.execute(ppa_contrato_proyectos_table.insert().values(
        contrato_id=cid, proyecto_id=planta_id))
    db.add(PPACompromisoEnergia(id=next(_expo_id), contrato_id=cid,
                                año=anio, mes=mes, energia_minima=energia_minima_mwh))
    return cid


def test_obligacion_prorrateo_con_join_planta(db_expo):
    """La obligación mensual del contrato se prorratea por día vía el join M:N."""
    # 310 MWh en julio (31 días) → 10 MWh/día.
    _add_contrato_con_compromiso(db_expo, planta_id=1, anio=2026, mes=7, energia_minima_mwh=310)
    db_expo.commit()
    obl = svc.get_ppa_obligacion_mwh_por_dia(db_expo, date(2026, 7, 1), date(2026, 7, 3), planta_id=1)
    assert obl[date(2026, 7, 1)] == pytest.approx(10.0)
    assert obl[date(2026, 7, 2)] == pytest.approx(10.0)
    # Otra planta no inscrita en el contrato → sin obligación.
    obl_otra = svc.get_ppa_obligacion_mwh_por_dia(db_expo, date(2026, 7, 1), date(2026, 7, 1), planta_id=999)
    assert obl_otra == {}


def test_historical_no_fabrica_deficit_sin_generacion(db_expo):
    """Día con precio + obligación pero SIN generación cargada: exposición None,
    datos_completos False, y NO entra en los indicadores (no fabrica déficit)."""
    dia = date(2026, 7, 10)
    _add_precio_dia(db_expo, dia, 300_000)
    _add_contrato_con_compromiso(db_expo, planta_id=1, anio=2026, mes=7, energia_minima_mwh=310)
    db_expo.commit()

    res = svc.get_historical_exposure(db_expo, dia, dia, planta_id=1)
    assert len(res["puntos"]) == 1
    p = res["puntos"][0]
    assert p["generacion_mwh"] is None          # NO 0.0 fabricado
    assert p["ppa_obligacion_mwh"] == pytest.approx(10.0)
    assert p["exposicion_cop"] is None          # sin generación → sin exposición
    assert p["datos_completos"] is False
    # El día incompleto no contamina los indicadores.
    assert res["indicadores"]["n"] == 0
    assert res["indicadores"]["var_95_cop"] is None


def test_historical_dia_completo_calcula_exposicion(db_expo):
    """Día con las tres patas: exposición = (gen − obl) × precio, completo."""
    dia = date(2026, 7, 10)
    _add_precio_dia(db_expo, dia, 300_000)
    _add_generacion(db_expo, dia, planta_id=1, mwh=15)
    _add_contrato_con_compromiso(db_expo, planta_id=1, anio=2026, mes=7, energia_minima_mwh=310)
    db_expo.commit()

    res = svc.get_historical_exposure(db_expo, dia, dia, planta_id=1)
    p = res["puntos"][0]
    assert p["datos_completos"] is True
    # (15 − 10) × 300.000 = 1.500.000
    assert p["exposicion_cop"] == pytest.approx(1_500_000.0)
    assert res["indicadores"]["n"] == 1


def test_current_devuelve_ultimo_dia_completo_no_el_borde(db_expo):
    """`current` sin fecha usa el último día COMPLETO, no el último con precio
    (donde la generación aún no llegó → no debe fabricar un déficit)."""
    d_completo = date(2026, 7, 9)
    d_borde = date(2026, 7, 12)   # último con precio, sin generación
    _add_precio_dia(db_expo, d_completo, 300_000)
    _add_generacion(db_expo, d_completo, planta_id=1, mwh=15)
    _add_precio_dia(db_expo, d_borde, 320_000)   # sin generación
    _add_contrato_con_compromiso(db_expo, planta_id=1, anio=2026, mes=7, energia_minima_mwh=310)
    db_expo.commit()

    p = svc.calculate_current_exposure(db_expo, planta_id=1)
    assert p["fecha"] == d_completo
    assert p["datos_completos"] is True
    assert p["exposicion_cop"] == pytest.approx(1_500_000.0)


def test_current_sin_dia_completo_es_honesto(db_expo):
    """Si ningún día reciente tiene generación, `current` devuelve punto vacío
    (datos_completos False), nunca un déficit fabricado."""
    d_borde = date(2026, 7, 12)
    _add_precio_dia(db_expo, d_borde, 320_000)
    _add_contrato_con_compromiso(db_expo, planta_id=1, anio=2026, mes=7, energia_minima_mwh=310)
    db_expo.commit()

    p = svc.calculate_current_exposure(db_expo, planta_id=1)
    assert p["datos_completos"] is False
    assert p["exposicion_cop"] is None
    assert p["generacion_mwh"] is None


def test_parser_omite_precio_fuera_de_rango_numeric():
    """convertir_kwh_a_mwh=True sobre un archivo ya en COP/MWh: el ×1000 se sale
    de NUMERIC(10,2) → la fila se omite (no revienta el INSERT)."""
    # 200.000 COP/MWh × 1000 = 200.000.000 > 99.999.999,99 → omitida.
    csv = "fecha;0\n2026-07-01;200000\n".encode()
    filas = parse_xm_precio_bolsa_bytes(csv, convertir_kwh_a_mwh=True)
    assert filas == []
    # Sin conversión el mismo valor cabe.
    filas_ok = parse_xm_precio_bolsa_bytes(csv, convertir_kwh_a_mwh=False)
    assert len(filas_ok) == 1
    assert filas_ok[0]["precio_cop_mwh"] == Decimal("200000.00")
