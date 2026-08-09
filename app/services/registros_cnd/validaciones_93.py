"""Validaciones automaticas del requisito 9.3. Portado de src/lib/domain/validaciones93.ts.

Coherencia exigida:
  - Corrientes: Icc_pk > Icc_3F > Icc_2F >= Icc_1F   y   Icc_EE ~= In_eq
  - Voltajes:   V_max > V_nom > V_min
  - Relaciones tipicas (advertencia): Icc_pk ~= sqrt(2)*Icc_3F ; Icc_2F ~= 0.866*Icc_3F

Funciones puras. Un valor ausente NO es error: se marca PENDIENTE (nunca inventar datos).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

RAIZ2 = math.sqrt(2)  # 1.41421356...
K_2F = 0.866  # Icc_2F = 0.866 * Icc_3F
TOL_REL = 0.05  # 5% de tolerancia relativa para comparaciones "~="

# Severidad: "OK" | "ERROR" | "ADVERTENCIA" | "PENDIENTE"


@dataclass
class Entradas93:
    icc_subtrans_pico_kap: float | None = None   # Icc_pk (kAp)
    icc_subtrans_3f_ka: float | None = None       # Icc_3F (kA)
    icc_subtrans_2f_ka: float | None = None       # Icc_2F (kA)
    icc_subtrans_1f_ka: float | None = None       # Icc_1F (kA)
    icc_estado_estable_ka: float | None = None    # Icc_EE (kA)
    voltaje_max_kv: float | None = None
    voltaje_nominal_kv: float | None = None
    voltaje_min_kv: float | None = None
    in_eq_ka: float | None = None                 # In_eq (kA)


def _tiene(n) -> bool:
    return isinstance(n, (int, float)) and math.isfinite(n)


def _aprox_igual(a: float, b: float, tol_rel: float = TOL_REL) -> bool:
    escala = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / escala <= tol_rel


def _fmt(n: float) -> str:
    return f"{n:.4f}"


def validar_93(e: Entradas93) -> dict:
    """Ejecuta todas las validaciones del 9.3. `valido` es True solo si no hay ERROR."""
    r: list[dict] = []

    pk, i3, i2, i1 = (
        e.icc_subtrans_pico_kap, e.icc_subtrans_3f_ka,
        e.icc_subtrans_2f_ka, e.icc_subtrans_1f_ka,
    )

    # Icc_pk > Icc_3F
    if _tiene(pk) and _tiene(i3):
        if pk > i3:
            r.append({"regla": "Icc_pk > Icc_3F", "severidad": "OK", "mensaje": f"{_fmt(pk)} > {_fmt(i3)} kA"})
        else:
            r.append({"regla": "Icc_pk > Icc_3F", "severidad": "ERROR", "mensaje": f"Se esperaba Icc_pk ({_fmt(pk)}) > Icc_3F ({_fmt(i3)})"})
    else:
        r.append({"regla": "Icc_pk > Icc_3F", "severidad": "PENDIENTE", "mensaje": "Falta Icc_pk y/o Icc_3F"})

    # Icc_3F > Icc_2F
    if _tiene(i3) and _tiene(i2):
        if i3 > i2:
            r.append({"regla": "Icc_3F > Icc_2F", "severidad": "OK", "mensaje": f"{_fmt(i3)} > {_fmt(i2)} kA"})
        else:
            r.append({"regla": "Icc_3F > Icc_2F", "severidad": "ERROR", "mensaje": f"Se esperaba Icc_3F ({_fmt(i3)}) > Icc_2F ({_fmt(i2)})"})
    else:
        r.append({"regla": "Icc_3F > Icc_2F", "severidad": "PENDIENTE", "mensaje": "Falta Icc_3F y/o Icc_2F"})

    # Icc_2F >= Icc_1F
    if _tiene(i2) and _tiene(i1):
        if i2 >= i1:
            r.append({"regla": "Icc_2F >= Icc_1F", "severidad": "OK", "mensaje": f"{_fmt(i2)} >= {_fmt(i1)} kA"})
        else:
            r.append({"regla": "Icc_2F >= Icc_1F", "severidad": "ERROR", "mensaje": f"Se esperaba Icc_2F ({_fmt(i2)}) >= Icc_1F ({_fmt(i1)})"})
    else:
        r.append({"regla": "Icc_2F >= Icc_1F", "severidad": "PENDIENTE", "mensaje": "Falta Icc_2F y/o Icc_1F"})

    # Icc_EE ~= In_eq
    ee, ineq = e.icc_estado_estable_ka, e.in_eq_ka
    if _tiene(ee) and _tiene(ineq):
        if _aprox_igual(ee, ineq):
            r.append({"regla": "Icc_EE ~= In_eq", "severidad": "OK", "mensaje": f"{_fmt(ee)} ~= {_fmt(ineq)} kA"})
        else:
            r.append({"regla": "Icc_EE ~= In_eq", "severidad": "ERROR", "mensaje": f"Icc_EE ({_fmt(ee)}) deberia ser ~= In_eq ({_fmt(ineq)})"})
    else:
        r.append({"regla": "Icc_EE ~= In_eq", "severidad": "PENDIENTE", "mensaje": "Falta Icc_EE y/o In_eq (aportar In del datasheet)"})

    # V_max > V_nom > V_min
    vmax, vnom, vmin = e.voltaje_max_kv, e.voltaje_nominal_kv, e.voltaje_min_kv
    if _tiene(vmax) and _tiene(vnom) and _tiene(vmin):
        if vmax > vnom and vnom > vmin:
            r.append({"regla": "V_max > V_nom > V_min", "severidad": "OK", "mensaje": f"{vmax} > {vnom} > {vmin} kV"})
        else:
            r.append({"regla": "V_max > V_nom > V_min", "severidad": "ERROR", "mensaje": f"Orden invalido: max={vmax}, nom={vnom}, min={vmin} kV"})
    else:
        r.append({"regla": "V_max > V_nom > V_min", "severidad": "PENDIENTE", "mensaje": "Faltan uno o mas voltajes (max/nom/min)"})

    # Relaciones tipicas limitadas por control (advertencias)
    if _tiene(pk) and _tiene(i3):
        if not _aprox_igual(pk, RAIZ2 * i3):
            r.append({"regla": "Icc_pk ~= sqrt(2)*Icc_3F", "severidad": "ADVERTENCIA", "mensaje": f"Icc_pk={_fmt(pk)} vs sqrt(2)*Icc_3F={_fmt(RAIZ2 * i3)} (revisar)"})
        else:
            r.append({"regla": "Icc_pk ~= sqrt(2)*Icc_3F", "severidad": "OK", "mensaje": f"{_fmt(pk)} ~= {_fmt(RAIZ2 * i3)} kA"})
    if _tiene(i2) and _tiene(i3):
        if not _aprox_igual(i2, K_2F * i3):
            r.append({"regla": "Icc_2F ~= 0.866*Icc_3F", "severidad": "ADVERTENCIA", "mensaje": f"Icc_2F={_fmt(i2)} vs 0.866*Icc_3F={_fmt(K_2F * i3)} (revisar)"})
        else:
            r.append({"regla": "Icc_2F ~= 0.866*Icc_3F", "severidad": "OK", "mensaje": f"{_fmt(i2)} ~= {_fmt(K_2F * i3)} kA"})

    return {"valido": not any(x["severidad"] == "ERROR" for x in r), "resultados": r}


@dataclass
class CorrientesCortocircuito:
    in_eq: float
    icc_3f: float
    icc_pk: float
    icc_2f: float
    icc_1f: float
    icc_ee: float


def corrientes_desde_in_eq(in_eq: float, k: float = 1.5) -> CorrientesCortocircuito:
    """Deriva las corrientes de cortocircuito limitadas por control a partir de In_eq.

    Icc_3F = k*In_eq (k~=1.5) ; Icc_pk = sqrt(2)*Icc_3F ; Icc_2F = 0.866*Icc_3F ;
    Icc_1F = Icc_3F ; Icc_EE = In_eq. Redondeo a 4 decimales (como exige XM).
    """
    def r4(n: float) -> float:
        return round(n + 1e-12, 4)

    icc_3f = k * in_eq
    return CorrientesCortocircuito(
        in_eq=r4(in_eq),
        icc_3f=r4(icc_3f),
        icc_pk=r4(RAIZ2 * icc_3f),
        icc_2f=r4(K_2F * icc_3f),
        icc_1f=r4(icc_3f),
        icc_ee=r4(in_eq),
    )
