"""Derivación de la fecha de inicio de comercialización.

`primer_dia_con_generacion` es una función pura sobre lecturas de un contador
acumulado; devuelve el primer día (Col) con generación real. Se testea sin red.
`identificador_monitoreo` resuelve el identificador de la API con COALESCE.
"""
from datetime import date

from app.services.comercializacion import (
    primer_dia_con_generacion,
    identificador_monitoreo,
)


def _r(ts, gen):
    return {"time_stamp": ts, "generacion": gen}


def test_primer_dia_arranca_en_cero_luego_sube():
    # Caso Sabana: contador en 0 hasta que empieza a generar.
    readings = [
        _r("2026-06-01T00:00:00-05:00", 0.0),
        _r("2026-06-18T23:00:00-05:00", 0.0),
        _r("2026-06-19T11:00:00-05:00", 5.0),
        _r("2026-06-20T10:00:00-05:00", 12.0),
    ]
    dia, cum = primer_dia_con_generacion(readings)
    assert dia == date(2026, 6, 19)
    assert cum == 5.0


def test_sin_generacion_devuelve_none():
    readings = [
        _r("2026-06-01T00:00:00-05:00", 0.0),
        _r("2026-06-02T00:00:00-05:00", 0.0),
    ]
    dia, _ = primer_dia_con_generacion(readings)
    assert dia is None


def test_ya_generando_al_inicio_toma_primer_dia_positivo():
    # La ventana arranca cuando la planta ya venía generando (nunca vemos el 0):
    # fallback al primer día con valor positivo.
    readings = [
        _r("2025-01-10T08:00:00-05:00", 100.0),
        _r("2025-01-11T08:00:00-05:00", 130.0),
    ]
    dia, _ = primer_dia_con_generacion(readings)
    assert dia == date(2025, 1, 10)


def test_ignora_lecturas_nulas():
    readings = [
        _r("2026-03-01T00:00:00-05:00", None),
        _r("2026-03-02T00:00:00-05:00", 0.0),
        _r("2026-03-03T00:00:00-05:00", 4.0),
    ]
    dia, _ = primer_dia_con_generacion(readings)
    assert dia == date(2026, 3, 3)


def test_continuacion_entre_bloques_con_prev_cum():
    # Mes 1 termina en 10 sin haber detectado subida (arrancó ya en 10). Mes 2
    # sube a 15 respecto al acumulado previo → primer día = ese día del mes 2.
    mes2 = [_r("2026-05-02T09:00:00-05:00", 15.0)]
    dia, cum = primer_dia_con_generacion(mes2, prev_cum=10.0)
    assert dia == date(2026, 5, 2)
    assert cum == 15.0


def test_identificador_monitoreo_coalesce():
    class P:
        sub_project = None
        topic_slug = "sabana_de_torres"
    assert identificador_monitoreo(P()) == "sabana_de_torres"

    class Q:
        sub_project = "sp_x"
        topic_slug = "slug_z"
    assert identificador_monitoreo(Q()) == "sp_x"

    class R:
        sub_project = None
        topic_slug = None
    assert identificador_monitoreo(R()) is None
