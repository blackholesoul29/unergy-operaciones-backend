"""Lógica pura del módulo Retos Q: semanas, consolidado, meta esperada y estado."""
from datetime import date

import pytest

from app.services import retos as svc


# ---------------------------------------------------------------------------
# rango_trimestre
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("q,esperado", [
    (1, (date(2026, 1, 1), date(2026, 3, 31))),
    (2, (date(2026, 4, 1), date(2026, 6, 30))),
    (3, (date(2026, 7, 1), date(2026, 9, 30))),
    (4, (date(2026, 10, 1), date(2026, 12, 31))),
])
def test_rango_trimestre(q, esperado):
    assert svc.rango_trimestre(2026, q) == esperado


def test_rango_trimestre_invalido():
    with pytest.raises(ValueError):
        svc.rango_trimestre(2026, 5)


# ---------------------------------------------------------------------------
# generar_semanas
# ---------------------------------------------------------------------------

def test_semanas_q3_2026_arranca_a_mitad_de_semana():
    """Q3 2026 empieza el miércoles 1-jul: la S1 arranca el lunes 29-jun."""
    inicio, fin = svc.rango_trimestre(2026, 3)
    semanas = svc.generar_semanas(inicio, fin, hoy=date(2026, 8, 14))

    assert len(semanas) == 14
    s1 = semanas[0]
    assert s1["numero"] == 1
    assert s1["inicio"] == date(2026, 6, 29)          # lunes
    assert s1["fin"] == date(2026, 7, 5)              # domingo
    assert s1["inicio_efectivo"] == date(2026, 7, 1)  # recortado al rango del Q
    assert s1["fin_efectivo"] == date(2026, 7, 5)
    assert s1["etiqueta"] == "S1"
    assert s1["rango_label"] == "29 jun–5 jul"        # cruza mes
    assert s1["parcial"] is True

    ultima = semanas[-1]
    assert ultima["numero"] == 14
    assert ultima["inicio"] == date(2026, 9, 28)
    assert ultima["fin"] == date(2026, 10, 4)
    assert ultima["fin_efectivo"] == date(2026, 9, 30)
    assert ultima["parcial"] is True


def test_semanas_todas_arrancan_en_lunes_y_son_consecutivas():
    inicio, fin = svc.rango_trimestre(2026, 3)
    semanas = svc.generar_semanas(inicio, fin, hoy=date(2026, 8, 14))
    for i, s in enumerate(semanas):
        assert s["inicio"].weekday() == 0
        assert s["numero"] == i + 1
        if i:
            assert (s["inicio"] - semanas[i - 1]["inicio"]).days == 7


def test_semana_completa_no_es_parcial_y_label_dentro_del_mes():
    # 5-ene-2026 es lunes: el rango arranca justo en lunes.
    semanas = svc.generar_semanas(date(2026, 1, 5), date(2026, 1, 18), hoy=date(2026, 1, 5))
    assert len(semanas) == 2
    assert semanas[0]["parcial"] is False
    assert semanas[0]["rango_label"] == "5–11 ene"
    assert semanas[1]["rango_label"] == "12–18 ene"


def test_semanas_cruzando_anio():
    """Un Q que cruza el cambio de año: la numeración sigue corrida."""
    semanas = svc.generar_semanas(date(2026, 12, 15), date(2027, 1, 15), hoy=date(2026, 12, 20))
    assert semanas[0]["inicio"] == date(2026, 12, 14)  # lunes previo al 15-dic
    assert semanas[0]["rango_label"] == "14–20 dic"
    assert semanas[-1]["fin"] >= date(2027, 1, 15)
    numeros = [s["numero"] for s in semanas]
    assert numeros == list(range(1, len(semanas) + 1))
    # El cambio de año no reinicia la numeración ni rompe el label.
    cruce = [s for s in semanas if s["inicio"].year == 2026 and s["fin"].year == 2027]
    assert cruce and cruce[0]["rango_label"] == "28 dic–3 ene"


def test_tope_duro_de_60_semanas():
    semanas = svc.generar_semanas(date(2026, 1, 5), date(2030, 1, 1), hoy=date(2026, 1, 5))
    assert len(semanas) == 60
    assert semanas[-1]["numero"] == 60
    # contar_semanas NO aplica el tope (es lo que valida el rango antes de guardar)
    assert svc.contar_semanas(date(2026, 1, 5), date(2030, 1, 1)) > 60


def test_contar_semanas():
    assert svc.contar_semanas(date(2026, 1, 5), date(2026, 1, 11)) == 1
    assert svc.contar_semanas(date(2026, 1, 5), date(2026, 1, 12)) == 2
    inicio, fin = svc.rango_trimestre(2026, 3)
    assert svc.contar_semanas(inicio, fin) == 14


def test_marcas_actual_y_futura():
    inicio, fin = svc.rango_trimestre(2026, 3)
    semanas = svc.generar_semanas(inicio, fin, hoy=date(2026, 8, 14))
    actuales = [s for s in semanas if s["es_actual"]]
    assert len(actuales) == 1
    assert actuales[0]["inicio"] <= date(2026, 8, 14) <= actuales[0]["fin"]
    assert all(s["es_futura"] for s in semanas if s["inicio"] > date(2026, 8, 14))
    assert not any(s["es_futura"] for s in semanas if s["inicio"] <= date(2026, 8, 14))


# ---------------------------------------------------------------------------
# semana actual / transcurridas / estado del periodo
# ---------------------------------------------------------------------------

def test_semana_actual_y_transcurridas():
    inicio, fin = svc.rango_trimestre(2026, 3)
    semanas = svc.generar_semanas(inicio, fin, hoy=date(2026, 8, 14))

    # 14-ago-2026 cae en la semana 7 (lunes 10-ago).
    assert svc.numero_semana_actual(semanas, inicio, fin, date(2026, 8, 14)) == 7
    # Pero solo 6 semanas están CERRADAS: la 7 va corriendo y todavía no se le
    # puede exigir su aporte a la meta.
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 8, 14)) == 6

    # El domingo que cierra la semana 7 sí la cuenta.
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 8, 16)) == 7

    # Arrancando el Q no hay ninguna semana cerrada: sin ritmo que exigir.
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 7, 1)) == 0

    # El último día del trimestre cuenta todas, aunque su semana ISO siga abierta.
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 9, 30)) == 14


def test_semana_actual_none_fuera_de_rango():
    inicio, fin = svc.rango_trimestre(2026, 3)
    semanas = svc.generar_semanas(inicio, fin, hoy=date(2026, 6, 30))
    # 30-jun cae dentro de la S1 (lunes 29-jun) pero fuera del rango del Q.
    assert svc.numero_semana_actual(semanas, inicio, fin, date(2026, 6, 30)) is None
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 6, 30)) == 0
    assert svc.semanas_transcurridas(semanas, inicio, fin, date(2026, 12, 1)) == 14


def test_estado_periodo():
    inicio, fin = svc.rango_trimestre(2026, 3)
    assert svc.estado_periodo(inicio, fin, date(2026, 5, 1)) == "proximo"
    assert svc.estado_periodo(inicio, fin, date(2026, 8, 14)) == "en_curso"
    assert svc.estado_periodo(inicio, fin, date(2026, 7, 1)) == "en_curso"
    assert svc.estado_periodo(inicio, fin, date(2026, 9, 30)) == "en_curso"
    assert svc.estado_periodo(inicio, fin, date(2026, 10, 1)) == "cerrado"


# ---------------------------------------------------------------------------
# consolidar
# ---------------------------------------------------------------------------

def test_consolidar_las_cuatro_agregaciones():
    valores = [10.0, None, 30.0, 20.0, None]
    assert svc.consolidar(valores, "suma") == 60.0
    assert svc.consolidar(valores, "promedio") == 20.0
    assert svc.consolidar(valores, "ultimo") == 20.0   # semana 4, la más alta con dato
    assert svc.consolidar(valores, "maximo") == 30.0


def test_consolidar_sin_datos_es_none():
    for tipo in svc.TIPOS_AGREGACION:
        assert svc.consolidar([None, None, None], tipo) is None
        assert svc.consolidar([], tipo) is None


def test_consolidar_ultimo_ignora_las_semanas_vacias_del_final():
    assert svc.consolidar([5.0, 7.0, None, None], "ultimo") == 7.0


def test_consolidar_tipo_desconocido_cae_en_suma():
    assert svc.consolidar([1.0, 2.0], "loquesea") == 3.0


# ---------------------------------------------------------------------------
# meta esperada
# ---------------------------------------------------------------------------

def test_meta_esperada_suma_se_prorratea():
    assert svc.meta_esperada(1200, "suma", 7, 14) == 600.0
    assert svc.meta_esperada(1200, "suma", 0, 14) == 0.0
    assert svc.meta_esperada(1200, "suma", 14, 14) == 1200.0


def test_meta_esperada_resto_no_se_prorratea():
    for tipo in ("promedio", "ultimo", "maximo"):
        assert svc.meta_esperada(1200, tipo, 7, 14) == 1200.0


def test_meta_esperada_sin_meta_es_none():
    assert svc.meta_esperada(None, "suma", 7, 14) is None
    assert svc.meta_esperada(100, "suma", 1, 0) is None


def test_meta_esperada_acota_las_semanas_corridas():
    assert svc.meta_esperada(1200, "suma", 99, 14) == 1200.0
    assert svc.meta_esperada(1200, "suma", -3, 14) == 0.0


# ---------------------------------------------------------------------------
# porcentajes y estado
# ---------------------------------------------------------------------------

def test_avance_y_cumplimiento_mayor_mejor():
    assert svc.avance_pct(640.5, 1200) == pytest.approx(53.375)
    assert svc.cumplimiento_pct(640.5, 600.0, "mayor_mejor") == pytest.approx(106.75)
    assert svc.avance_pct(640.5, None) is None
    assert svc.avance_pct(640.5, 0) is None
    assert svc.cumplimiento_pct(None, 600.0, "mayor_mejor") is None
    assert svc.cumplimiento_pct(10.0, 0, "mayor_mejor") is None


def test_cumplimiento_menor_mejor_se_invierte():
    # Gastar 80 cuando lo esperado era 100 es cumplir de más.
    assert svc.cumplimiento_pct(80.0, 100.0, "menor_mejor") == pytest.approx(125.0)
    assert svc.cumplimiento_pct(125.0, 100.0, "menor_mejor") == pytest.approx(80.0)


@pytest.mark.parametrize("consolidado,esperado", [
    (60.0, "en_riesgo"),   # 60%
    (69.9, "en_riesgo"),
    (70.0, "atencion"),
    (99.9, "atencion"),
    (100.0, "cumple"),
    (109.9, "cumple"),
    (110.0, "excede"),
    (300.0, "excede"),
])
def test_clasificar_estado_mayor_mejor(consolidado, esperado):
    assert svc.clasificar_estado(consolidado, 100.0, "mayor_mejor") == esperado


@pytest.mark.parametrize("consolidado,esperado", [
    (200.0, "en_riesgo"),   # 50%
    (143.0, "en_riesgo"),
    (142.0, "atencion"),    # ~70.4%
    (101.0, "atencion"),
    (100.0, "cumple"),
    (91.0, "cumple"),       # ~109.9%
    (90.0, "excede"),       # ~111%
    (0.0, "excede"),        # cero es el mejor caso posible
])
def test_clasificar_estado_menor_mejor(consolidado, esperado):
    assert svc.clasificar_estado(consolidado, 100.0, "menor_mejor") == esperado


def test_clasificar_estado_sin_datos():
    assert svc.clasificar_estado(None, 100.0, "mayor_mejor") == "sin_datos"
    # Sin meta contra la cual medir no hay semáforo.
    assert svc.clasificar_estado(50.0, None, "mayor_mejor") == "sin_datos"
    assert svc.clasificar_estado(50.0, 0, "mayor_mejor") == "sin_datos"


def test_promedio_cumplimiento():
    assert svc.promedio_cumplimiento([100.0, 50.0, None]) == 75.0
    assert svc.promedio_cumplimiento([None, None]) is None
    assert svc.promedio_cumplimiento([]) is None


def test_redondear():
    assert svc.redondear(None) is None
    assert svc.redondear(53.375, 1) == 53.4
    assert svc.redondear(1 / 3) == 0.3333
