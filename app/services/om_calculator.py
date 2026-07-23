"""
Lógica de cálculo O&M — pura, sin dependencias de DB ni FastAPI.
Todas las funciones son deterministas dado el mismo input.

Indexación IPC (regla vigente — por ANIVERSARIO REAL del contrato):
- fecha_base = fecha_inicio_om (fecha de inicio O&M); si no hay, fecha_firma_contrato
  como respaldo. La fecha de suscripción NO indexa: solo es informativa cuando existe
  un inicio O&M.
- Cada aniversario de fecha_base (mismo mes/día, año fecha_base.year + k, con clamp a
  28-feb si fecha_base cae en 29-feb y el año del aniversario no es bisiesto) activa la
  tasa IPC del AÑO CALENDARIO en que cae ese aniversario — no la del 1-enero.
- Un aniversario solo cuenta si ya ocurrió al último día del período que se factura.
- factor = ∏ (1 + tasa[año_aniversario]) para cada aniversario cumplido con tasa cargada.
- Si el contrato aún no cumple su primer aniversario en el período → sin aniversarios
  cumplidos → factor = 1.0 (sale naturalmente del cálculo, sin caso especial).
"""
from __future__ import annotations
import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


# ── Emparejamiento de nombres de proyecto (seed ↔ contrato existente) ─────────

_OM_GENERIC = {"la", "el", "los", "las", "de", "del", "san", "sur", "norte",
               "solar", "minigranja", "valle"}


def om_norm(s: str) -> str:
    """Minúsculas, sin acentos, sin espacios extremos."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def om_strip_code(s: str) -> str:
    """Quita el prefijo de código del proyecto, ej. 'MGS 0021 - ' → ''."""
    return re.sub(r"^mgs\s*\d+\s*-?\s*", "", om_norm(s)).strip()


def om_keys(nombre: str) -> list[str]:
    """Tokens significativos de un nombre de proyecto del seed (para emparejar)."""
    n = om_norm(nombre).replace("minigranja solar", " ").replace("minigranja", " ")
    toks = re.findall(r"[a-z]+|\d+", n)
    sig = [t for t in toks if t.isdigit() or (len(t) > 3 and t not in _OM_GENERIC)]
    if sig:
        return sig
    return [t for t in toks if t not in _OM_GENERIC] or toks


def om_match_seed(nombre_contrato: str, seed_keys):
    """
    Empareja el nombre de un contrato existente con UNA entrada del seed.
    seed_keys: lista de (item, keys). Devuelve item si el match es único, si no None.
    Exige que TODOS los tokens del seed estén en el nombre (sin el código MGS),
    evitando colisiones como Valencia Oriente 1/2 o Chiriguana 2/4.
    """
    disp_toks = set(re.findall(r"[a-z]+|\d+", om_strip_code(nombre_contrato)))
    cands = [it for (it, k) in seed_keys if k and all(t in disp_toks for t in k)]
    return cands[0] if len(cands) == 1 else None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_periodo(periodo: str) -> tuple[int, int]:
    """'2026-06' → (2026, 6)"""
    parts = periodo.split("-")
    return int(parts[0]), int(parts[1])


def _ultimo_dia_mes(año: int, mes: int) -> int:
    return calendar.monthrange(año, mes)[1]


_MESES_PERIODO = {"mensual": 1, "bimestral": 2, "trimestral": 3, "semestral": 6, "anual": 12}


def corresponde_cobro_este_mes(periodicidad, fecha_base: date, periodo: str) -> bool:
    """True si al mes `periodo` (YYYY-MM) le toca cobro según la periodicidad,
    contando ciclos desde el mes de `fecha_base`. Meses previos al inicio → False."""
    paso = _MESES_PERIODO.get((periodicidad or "mensual").lower(), 1)
    año_p, mes_p = _parse_periodo(periodo)
    meses = (año_p - fecha_base.year) * 12 + (mes_p - fecha_base.month)
    return meses >= 0 and meses % paso == 0


# ── Aniversarios del contrato ─────────────────────────────────────────────────

def _fecha_aniversario(fecha_base: date, k: int) -> date:
    """k-ésimo aniversario de fecha_base (mismo mes/día; clamp 29-feb → 28-feb)."""
    año = fecha_base.year + k
    mes = fecha_base.month
    dia = min(fecha_base.day, _ultimo_dia_mes(año, mes))
    return date(año, mes, dia)


def _aniversarios_cumplidos(
    fecha_base: date,
    año_periodo: int,
    mes_periodo: int,
) -> list[date]:
    """Fechas de aniversario (fecha_base + k años) ya alcanzadas al último día del período."""
    ultimo_dia_periodo = date(año_periodo, mes_periodo, _ultimo_dia_mes(año_periodo, mes_periodo))
    aniversarios: list[date] = []
    k = 1
    while True:
        fecha_aniv = _fecha_aniversario(fecha_base, k)
        if fecha_aniv > ultimo_dia_periodo:
            return aniversarios
        aniversarios.append(fecha_aniv)
        k += 1


# ── Factor acumulado IPC ──────────────────────────────────────────────────────

def factor_acumulado(aniversarios: list[date], ipc_tasas: dict[int, float]) -> float:
    """
    Producto de (1 + tasa) para cada aniversario cumplido cuyo año tenga tasa cargada.

    Las tasas se indexan por AÑO DE APLICACIÓN directo (no por año DANE - 1): la tasa
    del año en que cae el aniversario es la que se aplica desde ese aniversario.
    Si `aniversarios` está vacío (contrato aún no cumple un año) → factor = 1.0.
    """
    factor = 1.0
    for fecha_aniv in aniversarios:
        tasa = ipc_tasas.get(fecha_aniv.year)
        if tasa is not None:
            factor *= (1.0 + tasa)
    return factor


def _n_indexaciones(aniversarios: list[date], ipc_tasas: dict[int, float]) -> int:
    return sum(1 for f in aniversarios if f.year in ipc_tasas)


# ── Historial de indexaciones ────────────────────────────────────────────────

def ipc_incompleto(aniversarios: list[date], ipc_tasas: dict[int, float]) -> bool:
    """True si algún aniversario cumplido cae en un año sin tasa IPC cargada."""
    return any(f.year not in ipc_tasas for f in aniversarios)


def historial_indexaciones(aniversarios: list[date], ipc_tasas: dict[int, float]) -> str:
    """
    String legible del historial de IPC aplicados, con la fecha de cada aniversario.

    Ejemplo: "IPC 2025 (15-nov): 5.20% → IPC 2026 (15-nov): 5.10% | Acum: 10.57%"
    Si no hay indexación: "Sin indexación (aún no cumple un año)"
    """
    pasos = []
    factor = 1.0
    falta = False
    for fecha_aniv in aniversarios:
        tasa = ipc_tasas.get(fecha_aniv.year)
        if tasa is None:
            falta = True
            pasos.append(f"⚠ IPC {fecha_aniv.year} ({fecha_aniv.strftime('%d-%b')}): sin tasa cargada")
            continue
        factor *= (1.0 + tasa)
        pasos.append(f"IPC {fecha_aniv.year} ({fecha_aniv.strftime('%d-%b')}): {tasa * 100:.2f}%")
    if not pasos:
        return "Sin indexación (aún no cumple un año)"
    resumen = f" | Acum: {(factor - 1.0) * 100:.2f}%"
    if falta:
        resumen += " (parcial: falta tasa IPC)"
    return " → ".join(pasos) + resumen


# ── Prorrateo primer mes ──────────────────────────────────────────────────────

def calcular_prorrateo(
    fecha_operacion: date,
    periodo: str,
) -> tuple[str, float]:
    """
    Determina si el mes se cobra completo, parcial o no se cobra, según la
    fecha de inicio de operación.

    Reglas:
    - Si el período es posterior al mes de inicio → mes completo (1.0).
    - Si el período es el mes de inicio:
        * dias_operados = días desde fecha_operacion hasta fin de mes (inclusive)
        * Si dias_operados <= 15 → "No se factura" (0.0)
        * Si dias_operados > 15  → "X/Y días" (X/Y)

    Returns:
        (label, factor) donde factor ∈ [0.0, 1.0]
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    ultimo = _ultimo_dia_mes(año_periodo, mes_periodo)
    primer_dia_periodo = date(año_periodo, mes_periodo, 1)

    # Periodo posterior al mes de inicio → completo
    if primer_dia_periodo > date(fecha_operacion.year, fecha_operacion.month, 1):
        return "Completo", 1.0

    # Mismo mes que el inicio
    if (fecha_operacion.year, fecha_operacion.month) == (año_periodo, mes_periodo):
        dias_operados = ultimo - fecha_operacion.day + 1
        if dias_operados <= 15:
            return "No se factura", 0.0
        factor = round(dias_operados / ultimo, 6)
        return f"{dias_operados}/{ultimo} días", factor

    # Periodo anterior al mes de inicio
    return "No se factura", 0.0


# ── Cálculo principal ─────────────────────────────────────────────────────────

def calcular_proyecto(
    *,
    contrato_id: int,
    nombre_proyecto: str,
    fecha_firma_contrato: date | None,
    fecha_inicio_om: date | None,
    valor_base_anual: float | None,
    periodo: str,
    ipc_tasas: dict[int, float],
    incluido: bool = True,
    facturado: bool = False,
    valor_manual: float | None = None,
    valor_congelado: int | None = None,
    periodicidad: str | None = None,
) -> dict:
    """
    Calcula todos los campos de la fila O&M para un contrato en un período.

    Requiere `valor_base_anual` y una fecha base de indexación (`fecha_inicio_om`,
    o `fecha_firma_contrato` como respaldo); si falta alguno, la fila se marca
    deshabilitada (advertencia en UI) y no se factura.
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    mes_label = _mes_nombre(mes_periodo)

    def _deshabilitada(historial: str) -> dict:
        return {
            "contrato_id": contrato_id,
            "nombre_proyecto": nombre_proyecto,
            "periodo": periodo,
            "mes_año": f"{mes_label} {año_periodo}",
            "habilitado": False,
            "incluido": False,
            "facturado": facturado,
            "valor_base_anual": valor_base_anual,
            "n_indexaciones": 0,
            "factor_acumulado": 1.0,
            "valor_anual_indexado": None,
            "valor_mes_completo": None,
            "prorrateo_label": "—",
            "prorrateo_factor": 0.0,
            "valor_calculado": None,
            "editado_manual": False,
            "valor_a_facturar": None,
            "historial_indexaciones": historial,
        }

    tiene_valor = bool(valor_base_anual and valor_base_anual > 0)
    if not tiene_valor:
        return _deshabilitada("Sin valor base")

    # ── Fecha base = inicio O&M (respaldo: fecha de suscripción) ───────────────
    # La indexación se cuenta desde el inicio de operación (O&M). La suscripción
    # solo se usa como respaldo cuando no hay inicio O&M cargado.
    fecha_base = fecha_inicio_om if fecha_inicio_om is not None else fecha_firma_contrato
    if fecha_base is None:
        return _deshabilitada("Sin fecha de inicio O&M")

    aplica_este_mes = corresponde_cobro_este_mes(periodicidad, fecha_base, periodo)

    aniversarios = _aniversarios_cumplidos(fecha_base, año_periodo, mes_periodo)
    factor = factor_acumulado(aniversarios, ipc_tasas)
    n_idx = _n_indexaciones(aniversarios, ipc_tasas)

    valor_anual_indexado = valor_base_anual * factor
    valor_mes_completo = valor_anual_indexado / 12

    # Prorrateo sobre el inicio de operación real (si existe), si no la firma.
    fecha_operacion = fecha_inicio_om if fecha_inicio_om is not None else fecha_firma_contrato
    prorrateo_label, prorrateo_factor = calcular_prorrateo(fecha_operacion, periodo)

    valor_calculado = _redondear(valor_mes_completo * prorrateo_factor)
    editado_manual = valor_manual is not None
    valor_a_facturar = _redondear(float(valor_manual)) if editado_manual else valor_calculado
    if valor_congelado is not None:
        valor_a_facturar = int(valor_congelado)   # #4: mes ya facturado → valor congelado
    # #6: el override quedó desactualizado si ya no coincide con el valor recalculado
    # (p.ej. tras corregir la tasa IPC del año). El override se sigue respetando.
    valor_manual_desactualizado = editado_manual and _redondear(float(valor_manual)) != valor_calculado

    return {
        "contrato_id":          contrato_id,
        "nombre_proyecto":      nombre_proyecto,
        "periodo":              periodo,
        "mes_año":              f"{mes_label} {año_periodo}",
        "habilitado":           True,
        "incluido":             incluido,
        "facturado":            facturado,
        "valor_base_anual":     valor_base_anual,
        "n_indexaciones":       n_idx,
        "factor_acumulado":     round(factor, 6),
        "valor_anual_indexado": _redondear(valor_anual_indexado),
        "valor_mes_completo":   _redondear(valor_mes_completo),
        "prorrateo_label":      prorrateo_label,
        "prorrateo_factor":     prorrateo_factor,
        "valor_calculado":      valor_calculado,
        "editado_manual":       editado_manual,
        "valor_manual_desactualizado": valor_manual_desactualizado,
        "valor_a_facturar":     valor_a_facturar,
        "historial_indexaciones": historial_indexaciones(aniversarios, ipc_tasas),
        "valor_facturado_congelado": int(valor_congelado) if valor_congelado is not None else None,
        "aplica_este_mes":        aplica_este_mes,
        "periodicidad":           periodicidad,
        "ipc_incompleto":         ipc_incompleto(aniversarios, ipc_tasas),
    }


# ── Utilidades ────────────────────────────────────────────────────────────────

def _redondear(v: float) -> int:
    """Redondea al entero más cercano (COP no tiene decimales)."""
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mes_nombre(mes: int) -> str:
    MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return MESES[mes - 1]
