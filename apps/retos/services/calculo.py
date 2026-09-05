"""Lógica pura del módulo "Retos Q" (tablero trimestral de retos del equipo).

Todo lo que hay aquí es determinístico y sin sesión de base de datos: generación
de semanas a partir del rango del trimestre, consolidación de los valores
semanales, meta esperada prorrateada y clasificación de estado. El router
(`api/v1/retos/views.py`) solo consulta, llama a estas funciones y arma el schema.

Referencia normativa: CONTRATO_RETOS_Q.md secciones 3 y 4.
"""

from datetime import date, timedelta
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Constantes del dominio
# ---------------------------------------------------------------------------

TOPE_SEMANAS = 60

TIPOS_AGREGACION = ("suma", "promedio", "ultimo", "maximo")
DIRECCIONES = ("mayor_mejor", "menor_mejor")
ESTADOS = ("sin_datos", "en_riesgo", "atencion", "cumple", "excede")
ESTADOS_PERIODO = ("proximo", "en_curso", "cerrado")

# Meses abreviados en español, sin punto (el back manda el label ya formateado
# para que el front no reimplemente el formateo).
MESES_ABREV = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)

# Guion medio (en dash) usado en los rangos: "6–12 ene".
_GUION = "–"

# Primer y último día de cada trimestre calendario.
_INICIO_TRIMESTRE = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
_FIN_TRIMESTRE = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


# ---------------------------------------------------------------------------
# Rango del trimestre
# ---------------------------------------------------------------------------

def rango_trimestre(anio: int, trimestre: int) -> tuple[date, date]:
    """Fechas de un trimestre calendario: Q1 1-ene→31-mar ... Q4 1-oct→31-dic."""
    if trimestre not in _INICIO_TRIMESTRE:
        raise ValueError(f"Trimestre inválido: {trimestre}")
    mi, di = _INICIO_TRIMESTRE[trimestre]
    mf, df = _FIN_TRIMESTRE[trimestre]
    return date(anio, mi, di), date(anio, mf, df)


def nombre_trimestre(anio: int, trimestre: int) -> str:
    return f"Retos Q{trimestre} {anio}"


# ---------------------------------------------------------------------------
# Semanas
# ---------------------------------------------------------------------------

def lunes_de(dia: date) -> date:
    """Lunes de la semana que contiene `dia`."""
    return dia - timedelta(days=dia.weekday())


def rango_label(inicio: date, fin: date) -> str:
    """`"6–12 ene"` si la semana no cruza mes, `"29 sep–5 oct"` si lo cruza."""
    mes_ini = MESES_ABREV[inicio.month - 1]
    mes_fin = MESES_ABREV[fin.month - 1]
    if inicio.month == fin.month and inicio.year == fin.year:
        return f"{inicio.day}{_GUION}{fin.day} {mes_fin}"
    return f"{inicio.day} {mes_ini}{_GUION}{fin.day} {mes_fin}"


def contar_semanas(fecha_inicio: date, fecha_fin: date) -> int:
    """Semanas que abarca el rango, SIN aplicar el tope de 60.

    Se usa para validar el rango antes de guardarlo (`generar_semanas` corta en
    60 y no sirve para detectar el exceso).
    """
    if fecha_fin < fecha_inicio:
        return 0
    return ((fecha_fin - lunes_de(fecha_inicio)).days // 7) + 1


def generar_semanas(
    fecha_inicio: date,
    fecha_fin: date,
    hoy: date | None = None,
) -> list[dict]:
    """Semanas del trimestre, ancladas al LUNES (contrato sección 3).

    Cada dict trae `numero`, `inicio` (lunes, clave de los valores), `fin`
    (domingo), `inicio_efectivo` / `fin_efectivo` (recortados al rango del Q),
    `etiqueta`, `rango_label`, `parcial`, `es_actual` y `es_futura`.
    Tope duro de 60 semanas.
    """
    hoy = hoy or date.today()
    semanas: list[dict] = []
    cursor = lunes_de(fecha_inicio)
    numero = 1
    while cursor <= fecha_fin and numero <= TOPE_SEMANAS:
        fin_semana = cursor + timedelta(days=6)
        semanas.append({
            "numero": numero,
            "inicio": cursor,
            "fin": fin_semana,
            "inicio_efectivo": max(cursor, fecha_inicio),
            "fin_efectivo": min(fin_semana, fecha_fin),
            "etiqueta": f"S{numero}",
            "rango_label": rango_label(cursor, fin_semana),
            "es_actual": cursor <= hoy <= fin_semana,
            "es_futura": cursor > hoy,
            "parcial": cursor < fecha_inicio or fin_semana > fecha_fin,
        })
        cursor += timedelta(days=7)
        numero += 1
    return semanas


def numero_semana_actual(semanas: Sequence[dict], fecha_inicio: date,
                         fecha_fin: date, hoy: date | None = None) -> int | None:
    """Número de la semana que contiene hoy; None si hoy está fuera del rango."""
    hoy = hoy or date.today()
    if hoy < fecha_inicio or hoy > fecha_fin:
        return None
    for s in semanas:
        if s["inicio"] <= hoy <= s["fin"]:
            return s["numero"]
    return None


def semanas_transcurridas(semanas: Sequence[dict], fecha_inicio: date,
                          fecha_fin: date, hoy: date | None = None) -> int:
    """Semanas ya CERRADAS del Q, acotado a [0, total_semanas].

    Se cuentan las semanas cuyo último día ya pasó, no la que va corriendo: los
    valores se registran por semana completa, así que exigir el aporte de la
    semana en curso dejaría el tablero permanentemente atrasado (una métrica
    perfectamente al día se vería en `atencion` todas las semanas).

    0 si el Q aún no empieza, total_semanas si ya cerró.
    """
    hoy = hoy or date.today()
    total = len(semanas)
    if hoy < fecha_inicio:
        return 0
    if hoy > fecha_fin:
        return total
    # `fin_efectivo` (recortado a fecha_fin) y no `fin`, para que la última
    # semana cuente el mismo día en que se acaba el trimestre.
    cerradas = sum(1 for s in semanas if s["fin_efectivo"] <= hoy)
    return max(0, min(cerradas, total))


def estado_periodo(fecha_inicio: date, fecha_fin: date,
                   hoy: date | None = None) -> str:
    """`proximo` | `en_curso` | `cerrado` contra la fecha de hoy."""
    hoy = hoy or date.today()
    if hoy < fecha_inicio:
        return "proximo"
    if hoy > fecha_fin:
        return "cerrado"
    return "en_curso"


# ---------------------------------------------------------------------------
# Consolidado y metas
# ---------------------------------------------------------------------------

def consolidar(valores_por_semana: Iterable[float | None],
               tipo_agregacion: str) -> float | None:
    """Consolida los valores semanales (contrato sección 4).

    `valores_por_semana` viene ordenado por número de semana ascendente, con
    None en las semanas sin dato (es exactamente la `serie` que se publica).
    Devuelve None si no hay ningún valor.
    """
    valores = [float(v) for v in valores_por_semana if v is not None]
    if not valores:
        return None
    if tipo_agregacion == "promedio":
        return sum(valores) / len(valores)
    if tipo_agregacion == "ultimo":
        # El último no nulo en orden de semana = el de la semana con número más alto.
        return valores[-1]
    if tipo_agregacion == "maximo":
        return max(valores)
    return sum(valores)  # "suma" y cualquier valor desconocido


def meta_esperada(meta: float | None, tipo_agregacion: str,
                  semanas_corridas: int, total_semanas: int) -> float | None:
    """Ritmo que se debería llevar hoy. Solo `suma` se prorratea."""
    if meta is None:
        return None
    meta = float(meta)
    if tipo_agregacion != "suma":
        return meta
    if total_semanas <= 0:
        return None
    return meta * max(0, min(semanas_corridas, total_semanas)) / total_semanas


def avance_pct(consolidado: float | None, meta: float | None) -> float | None:
    """`consolidado / meta * 100`; None si la meta es null o 0."""
    if consolidado is None or meta is None or float(meta) == 0:
        return None
    return float(consolidado) / float(meta) * 100


def cumplimiento_pct(consolidado: float | None, esperada: float | None,
                     direccion: str) -> float | None:
    """Cumplimiento contra la meta esperada a la fecha.

    `menor_mejor` invierte la razón. Si el consolidado es 0 en `menor_mejor` la
    razón es indefinida (división por cero): se devuelve None y el estado se
    resuelve como `excede` en `clasificar_estado`.
    """
    if consolidado is None or esperada is None or float(esperada) == 0:
        return None
    consolidado = float(consolidado)
    esperada = float(esperada)
    if direccion == "menor_mejor":
        if consolidado == 0:
            return None
        return esperada / consolidado * 100
    return consolidado / esperada * 100


def clasificar_estado(consolidado: float | None, esperada: float | None,
                      direccion: str) -> str:
    """`sin_datos` | `en_riesgo` | `atencion` | `cumple` | `excede`."""
    if consolidado is None:
        return "sin_datos"
    if esperada is None or float(esperada) == 0:
        # Sin meta contra la cual medir no hay semáforo posible.
        return "sin_datos"
    if direccion == "menor_mejor" and float(consolidado) == 0:
        return "excede"
    pct = cumplimiento_pct(consolidado, esperada, direccion)
    if pct is None:
        return "sin_datos"
    if pct < 70:
        return "en_riesgo"
    if pct < 100:
        return "atencion"
    if pct < 110:
        return "cumple"
    return "excede"


def promedio_cumplimiento(valores: Iterable[float | None]) -> float | None:
    """`avance_global_pct` del Q: promedio simple de los cumplimientos con dato."""
    pcts = [float(v) for v in valores if v is not None]
    if not pcts:
        return None
    return sum(pcts) / len(pcts)


def redondear(valor: float | None, decimales: int = 4) -> float | None:
    """Redondeo defensivo: evita colas de coma flotante en el JSON."""
    if valor is None:
        return None
    return round(float(valor), decimales)
