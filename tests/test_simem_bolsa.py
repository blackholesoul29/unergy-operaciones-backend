"""Conector SIMEM del precio de bolsa. Funciones puras: sin BD, sin red, sin reloj.
El fetch se prueba con httpx.MockTransport (sin red real)."""
from app.services.simem_bolsa import (
    _version_rank,
    promedio_diario_max_version,
    promedio_ultimos_n_dias,
)


def _rec(var, fechahora, version, valor):
    return {
        "CodigoVariable": var, "FechaHora": fechahora, "CodigoDuracion": "PT1H",
        "UnidadMedida": "COP/kWh", "Version": version, "Valor": valor,
    }


def test_version_rank_ordena_tx_numericas_y_finales():
    assert _version_rank("TX1") < _version_rank("TX2")
    assert _version_rank("TX2") < _version_rank("TXR")
    assert _version_rank("TXR") < _version_rank("TXF")
    # desconocida no rompe: cae al fondo
    assert _version_rank("???") < _version_rank("TX1")


def test_promedio_diario_toma_version_mas_alta_por_dia():
    # Día 01: TX1 (valor 100) y TX2 (valor 200) -> gana TX2 = 200
    # Día 02: solo TX1 (valor 300) -> 300
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Nal", "2026-08-01 01:00:00", "TX2", 200.0),
        _rec("PB_Nal", "2026-08-02 00:00:00", "TX1", 300.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 200.0, "2026-08-02": 300.0}


def test_promedio_diario_filtra_solo_pb_nal():
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Int", "2026-08-01 00:00:00", "TX1", 999.0),
        _rec("PB_Tie", "2026-08-01 00:00:00", "TX1", 888.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 100.0}


def test_promedio_diario_promedia_las_horas_del_dia():
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Nal", "2026-08-01 01:00:00", "TX1", 200.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 150.0}


def test_promedio_ultimos_n_dias_toma_los_mas_recientes():
    daily = {f"2026-08-0{d}": float(d) for d in range(1, 9)}  # 1..8
    # últimos 7 días conocidos = 02..08 -> promedio de 2,3,4,5,6,7,8 = 5.0
    assert promedio_ultimos_n_dias(daily, 7) == 5.0


def test_promedio_ultimos_n_dias_vacio_devuelve_none():
    assert promedio_ultimos_n_dias({}, 7) is None
