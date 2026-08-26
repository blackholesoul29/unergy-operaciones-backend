"""_descartar_picos_espurios() -- segundo chequeo, absoluto contra la
capacidad de la frontera (ver limite_plausible_kwh() en utils.py).

El chequeo original (mediana del propio dia x UMBRAL_PICO_MULTIPLO) es
ciego a un error CRONICO de escala de unidad -- si TODAS las lecturas del
dia estan igual de infladas (ej. un nodo que reporta en W en vez de kW,
ver comentario "Polaris 1/2, ~1.150x" en datos_crudos.py), ninguna se ve
atipica frente a la mediana del propio dia. El chequeo de capacidad,
externo al dia, si lo detecta."""
import pandas as pd

from app.services.reporte_energia import datos_crudos


def _fila(ts, app1):
    return {"time": ts, "app1": app1, "app2": 0, "app3": 0}


def test_error_cronico_de_escala_no_lo_detecta_la_mediana_pero_si_la_capacidad():
    """Todas las lecturas del dia consistentemente ~1000x infladas -- la
    mediana no marca nada atipico (todo es igual de alto), pero exceden
    la capacidad fisica de la frontera."""
    filas = [_fila(f"2026-08-26T{h:02d}:00:00", -500000) for h in range(6, 18)]  # -500 MW cada hora
    df = datos_crudos._descartar_picos_espurios(
        pd.DataFrame(filas), capacidad_efectiva_mw=0.99,
    )
    # limite = 0.99 * 1000 * 3 = 2970 kW -- 500.000 kW lo supera por mucho
    assert (df["app1"] == 0).all()


def test_lectura_dentro_del_margen_no_se_descarta():
    filas = [_fila(f"2026-08-26T{h:02d}:00:00", -800) for h in range(6, 18)]  # -800 kW, dentro de 2970
    df = datos_crudos._descartar_picos_espurios(
        pd.DataFrame(filas), capacidad_efectiva_mw=0.99,
    )
    assert (df["app1"] == -800).all()


def test_sin_capacidad_efectiva_solo_aplica_el_chequeo_de_mediana():
    """Compatibilidad hacia atrás -- sin capacidad_efectiva_mw, el
    comportamiento es igual que antes de este fix (solo mediana propia)."""
    filas = [_fila(f"2026-08-26T{h:02d}:00:00", -500000) for h in range(6, 18)]
    df = datos_crudos._descartar_picos_espurios(pd.DataFrame(filas))
    # todas las lecturas son iguales -- la mediana no marca ninguna como atípica
    assert (df["app1"] == -500000).all()


def test_pico_puntual_unico_significativo_lo_descarta_el_chequeo_de_capacidad():
    """Caso límite del chequeo de mediana original: si el único pico
    significativo del día ES el propio pico corrupto, la mediana se
    calcula sobre sí mismo y nunca se ve "atípica" -- el chequeo de
    capacidad cubre este hueco."""
    filas = [_fila("2026-08-26T12:00:00", -343964)]  # un solo pico, sin nada más con qué compararlo
    df = datos_crudos._descartar_picos_espurios(
        pd.DataFrame(filas), capacidad_efectiva_mw=0.99,
    )
    assert (df["app1"] == 0).all()
