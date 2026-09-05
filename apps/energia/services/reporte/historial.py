"""El histórico que alimenta el reporte: factor de pérdida, mediana y forma.

Puerto de `app/services/reporte_energia/historial.py`.

**Un día "completo" NO es lo mismo que un día confiable.** `completo` solo
certifica continuidad de telemetría, no que la lectura corresponda a generación
real: un día Caso 3 (estimado vía FP, sería circular), Caso 6 (apagado) u otro
Caso no confiable podía tener `completo=True` y colarse igual en la mediana antes
de que se agregara el filtro por Caso.

**Consumo NO filtra por `revisar_manualmente`** (decisión del 2026-08-26). Lo que
importa es si la FUENTE fue real —Caso 'Medidor' o 'CGM'—, no si ese día puntual
quedó marcado para revisar por otro motivo. La mediana sobre hasta 30 días sigue
siendo robusta a un outlier que se cuele.

**'CGM' cuenta como confiable en Consumo, y sin eso el módulo no arranca**:
ninguna frontera de consumo podría construir historial desde cero, porque
'Medidor' sin mediana previa SIEMPRE queda `revisar_manualmente=True` — no hay
una segunda fuente independiente, como sí la tiene Generación con los inversores.
"""

from __future__ import annotations

import random
from datetime import date

import pandas as pd

from apps.energia.models import ReporteEnergiaConsumo, ReporteEnergiaGeneracion
from apps.energia.services.reporte.utils import lista_a_curva

# Cuantos dias con dato hacen falta antes de confiar en una mediana. Con menos
# que esto no se estima: se deja sin valor y la frontera queda para revisar.
#
# Se quedaron atras en el port desde `app/services/reporte_energia/historial.py`
# (lineas 21-23), donde estan definidas con estos mismos valores. Al no existir,
# CADA frontera moria con `NameError: name 'MIN_DIAS_FORMA' is not defined` y la
# corrida entera terminaba con todo en "Error de clasificacion" -- verificado el
# 2026-09-05 corriendo el clasificador a mano para el 2026-09-04.
MIN_DIAS_FP      = 3    # minimo de dias con datos para calcular el factor de perdida
MIN_DIAS_FORMA   = 3    # minimo de dias con reporte confiable antes de usar mediana/forma
MIN_DIAS_CONSUMO = 3

DIAS_VENTANA     = 30

# Casos de Generación cuya curva se considera dato real y completo, apto
# para alimentar mediana/forma -- Caso 3 (estimado vía FP) y Caso 8 (crudos
# parciales) quedan fuera a propósito, igual que Caso 6 (apagado) y 0 (externo).
CASOS_CONFIABLES_GENERACION = {1, 2, 4, 5, 7}

# Rango de FP calculado que se considera físicamente plausible -- fuera de
# él no se confía en el número y se usa _fp_fallback() en su lugar.
# Reemplaza al override manual FP_FIJO por frontera que existía acá antes
# (eliminado 2026-09-02; nunca se activó en producción -- diccionario vacío,
# pendiente de confirmar el frontera_id real de "MGS 0028 COX - Chiriguaná
# Norte 1" del pipeline original, Reporte-Energia): con el umbral ya acotado
# por ambos lados, un histórico inestable cae solo en este rechazo, sin
# necesitar un override manual por proyecto.
#
# Piso -- ninguna conexión de generación distribuida a baja/media tensión
# pierde tanto (pérdidas técnicas de transformador/cable normalmente rondan
# 1-3%, ver regulación CREG de conexión). Subido de 0.9 a 0.95 (2026-09-02,
# decisión del usuario): 0.9 dejaba pasar como "plausible" hasta un 10% de
# pérdida, más de lo esperable en este tipo de conexión.
UMBRAL_FP_MUY_BAJO  = 0.95
# Techo -- FP = E_medidor/E_inversor es un factor de PÉRDIDA: el medidor
# debería leer igual o menos que el inversor, nunca más. Un ratio por
# encima de 1 no es una pérdida más chica, es señal de que algo más anda
# mal (doble conteo, calibración) y tampoco se confía en él (decisión del
# usuario, 2026-09-02).
UMBRAL_FP_MUY_ALTO  = 1.0
# Sin FP calculable del histórico, o fuera del rango plausible de arriba, se
# reporta un valor variado día a día dentro de este rango en vez de repetir
# siempre el mismo número fijo (decisión de negocio, 2026-08-19) --
# determinístico por frontera+fecha (ver _fp_fallback) para que no cambie si
# se re-consulta o se re-corre el mismo día.
FP_FALLBACK_RANGO = (0.990, 0.995)


def _fp_fallback(frontera_id: int, fecha: date) -> float:
    rng = random.Random(f"{frontera_id}:{fecha.isoformat()}")
    lo, hi = FP_FALLBACK_RANGO
    return round(rng.uniform(lo, hi), 4)



# ---------------------------------------------------------------------------
# Factor de pérdida (Generación)
# ---------------------------------------------------------------------------

def get_factor_perdida_detalle(frontera_id: int, fecha: date) -> tuple[float | None, float | None]:
    """Retorna (fp_usado, fp_calculado) para una frontera de Generación.

    fp_calculado: mediana de los ratios diarios (E_med/E_inv) de los últimos
    DIAS_VENTANA días ANTES de `fecha`, con medidor completo ese día, ambas
    energías > 0, Caso confiable (CASOS_CONFIABLES_GENERACION) y sin
    revisión manual -- mismo criterio de "día confiable" que ya usan
    get_mediana_generacion()/get_forma_generacion(). `completo` por sí solo
    no alcanza: solo certifica continuidad de telemetría, no que la lectura
    corresponda a generación real (ver dia_completo() en curvas.py) -- un
    día Caso 3 (estimado vía FP, sería circular), Caso 6 (apagado) u otro
    Caso no confiable podía tener completo=True y aun así colarse en la
    mediana antes de este filtro.

    fp_usado: lo que realmente se aplica -- un valor dentro de
    FP_FALLBACK_RANGO (variado por frontera+fecha, ver _fp_fallback) si
    fp_calculado está fuera de [UMBRAL_FP_MUY_BAJO, UMBRAL_FP_MUY_ALTO] o no
    hay histórico suficiente, o fp_calculado tal cual en el resto de los casos.
    """
    filas = (
        ReporteEnergiaGeneracion.objects
        .filter(
            frontera_id=frontera_id,
            fecha__lt=fecha,
            caso__in=CASOS_CONFIABLES_GENERACION,
            revisar_manualmente=False,
        )
        .order_by("-fecha")
        .values_list(
            "energia_medidor_principal_kwh", "energia_medidor_respaldo_kwh",
            "medidor_principal_completo", "medidor_respaldo_completo",
            "energia_solenium_kwh",
        )[:DIAS_VENTANA]
    )

    ratios = []
    for e_ppal, e_resp, comp_ppal, comp_resp, e_inv in filas:
        e_inv = float(e_inv or 0)
        if e_inv <= 0:
            continue
        usar_ppal = bool(e_ppal and float(e_ppal) > 0)
        e_med = float(e_ppal or 0) if usar_ppal else float(e_resp or 0)
        completo = bool(comp_ppal) if usar_ppal else bool(comp_resp)
        if e_med > 0 and completo:
            ratios.append(e_med / e_inv)

    fp_calculado = float(pd.Series(ratios).median()) if len(ratios) >= MIN_DIAS_FP else None

    if fp_calculado is None:
        return _fp_fallback(frontera_id, fecha), None

    if fp_calculado < UMBRAL_FP_MUY_BAJO or fp_calculado > UMBRAL_FP_MUY_ALTO:
        return _fp_fallback(frontera_id, fecha), fp_calculado

    return fp_calculado, fp_calculado


# ---------------------------------------------------------------------------
# Mediana / forma horaria -- Generación
# ---------------------------------------------------------------------------

def get_mediana_generacion(frontera_id: int, fecha: date) -> tuple[float | None, int]:
    """Mediana del total diario de los últimos DIAS_VENTANA días con Caso
    confiable Y sin revisión manual, ANTES de `fecha`."""
    totales = (
        ReporteEnergiaGeneracion.objects
        .filter(
            frontera_id=frontera_id,
            fecha__lt=fecha,
            caso__in=CASOS_CONFIABLES_GENERACION,
            revisar_manualmente=False,
        )
        .order_by("-fecha")
        .values_list("energia_final_kwh", flat=True)[:DIAS_VENTANA]
    )

    # energia_final_kwh puede ser NULL incluso en un Caso "confiable" (ej. un
    # registro editado a mano a medias, o un dato viejo previo a que el
    # clasificador siempre lo llenara) -- float(None) tumbaba toda la corrida
    # del dia (ver ejecutar_dia, sin try/except por frontera).
    validos = [float(t) for t in totales if t is not None]
    if len(validos) < MIN_DIAS_FORMA:
        return None, len(validos)
    return float(pd.Series(validos).median()), len(validos)


def get_forma_generacion(frontera_id: int, fecha: date) -> tuple[pd.Series | None, int]:
    """Forma horaria típica (24 valores) de los últimos DIAS_VENTANA días con
    Caso confiable, sin revisión manual y curva completa (sin huecos), ANTES
    de `fecha`. Cada día se normaliza a su propio total antes de combinarlos;
    se toma la MEDIANA por hora entre esos días normalizados.

    Retorna (forma, dias_usados). forma NO suma necesariamente 1 -- reescalar
    al total real con utils.escalar_curva(). None si hay menos de
    MIN_DIAS_FORMA días disponibles.
    """
    curvas = (
        ReporteEnergiaGeneracion.objects
        .filter(
            frontera_id=frontera_id,
            fecha__lt=fecha,
            caso__in=CASOS_CONFIABLES_GENERACION,
            revisar_manualmente=False,
        )
        .order_by("-fecha")
        .values_list("curva_final", flat=True)[:DIAS_VENTANA]
    )

    formas = []
    for valores in curvas:
        curva = lista_a_curva(valores)
        if curva.isna().any():
            continue  # día con huecos -- no aporta a la forma
        total = curva.sum()
        if total > 0:
            formas.append(curva / total)

    if len(formas) < MIN_DIAS_FORMA:
        return None, len(formas)

    forma_mediana = pd.concat(formas, axis=1).median(axis=1)
    return forma_mediana, len(formas)


# ---------------------------------------------------------------------------
# Mediana / forma horaria -- Consumo
# ---------------------------------------------------------------------------

CASOS_CONFIABLES_CONSUMO = ("Medidor", "CGM")


def get_mediana_consumo(frontera_id: int, fecha: date) -> tuple[float | None, int]:
    """Mediana del total diario de los últimos DIAS_VENTANA días de Caso
    'Medidor' o 'CGM', ANTES de `fecha`. 'Histórico' queda fuera (es ya una
    estimación, no lectura real). 'CGM' cuenta como confiable porque el
    reporte automático de Quoia es en sí una lectura real (ASIC), no una
    estimación.

    Ya NO se filtra por revisar_manualmente (quitado 2026-08-26, pedido de
    Sara: lo que importa es si la FUENTE fue real -- caso 'Medidor'/'CGM' --
    no si ese día puntual quedó marcado para revisar por otro motivo, ej.
    alejarse de la mediana). Antes esto también bloqueaba por completo el
    histórico de las fronteras que una lista de excepción dejaba siempre
    marcadas para revisar (ej. Paso Norte) -- esas listas se eliminaron el
    2026-09-02, pero la decisión de no filtrar sigue en pie: la mediana (sobre
    hasta 30 días) sigue siendo robusta a un outlier puntual aunque se
    cuele sin revisar.

    Sin este 'CGM', ninguna frontera de Consumo podría nunca construir
    historial desde cero: 'Medidor' sin mediana previa SIEMPRE queda
    revisar_manualmente=True (no hay una segunda fuente independiente tipo
    inversores, como sí tiene Generación, para autoconfirmarse el mismo
    día)."""
    totales = (
        ReporteEnergiaConsumo.objects
        .filter(
            frontera_id=frontera_id,
            fecha__lt=fecha,
            caso__in=CASOS_CONFIABLES_CONSUMO,
        )
        .order_by("-fecha")
        .values_list("energia_final_kwh", flat=True)[:DIAS_VENTANA]
    )

    validos = [float(t) for t in totales if t is not None]
    if len(validos) < MIN_DIAS_CONSUMO:
        return None, len(validos)
    return float(pd.Series(validos).median()), len(validos)


def get_forma_consumo(frontera_id: int, fecha: date) -> tuple[pd.Series | None, int]:
    """Forma horaria típica de Consumo, mismo criterio que get_mediana_consumo
    (Caso 'Medidor' o 'CGM', sin filtrar por revisar_manualmente)."""
    curvas = (
        ReporteEnergiaConsumo.objects
        .filter(
            frontera_id=frontera_id,
            fecha__lt=fecha,
            caso__in=CASOS_CONFIABLES_CONSUMO,
        )
        .order_by("-fecha")
        .values_list("curva_final", flat=True)[:DIAS_VENTANA]
    )

    formas = []
    for valores in curvas:
        curva = lista_a_curva(valores)
        if curva.isna().any():
            continue
        total = curva.sum()
        if total > 0:
            formas.append(curva / total)

    if len(formas) < MIN_DIAS_CONSUMO:
        return None, len(formas)

    forma_mediana = pd.concat(formas, axis=1).median(axis=1)
    return forma_mediana, len(formas)
