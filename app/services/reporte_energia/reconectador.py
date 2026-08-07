"""Reconectador (relay) de generación — API de Solenium, endpoint /relay/.

Puerto de process/src/internals/reconectador.py (repo Reporte-Energia).

No confundir con datos_crudos.py (canal crudo del NODO de Quoia, vars=ap) --
el reconectador es un dispositivo físico distinto, propio de Solenium, que
mide el punto de conexión de GENERACIÓN (solo aplica a generación, no a
consumo). No todos los proyectos lo tienen -- /relay/ retorna 404 cuando no
está instalado.

Se usa como segunda fuente (después de medidor/datos crudos, antes de la
curva de Solenium × FP) para rellenar horas puntuales que quedaron sin dato
dentro de un día que, en general, sí tiene información real.

Convención de signo -- NO es universal entre proyectos: se toma el VALOR
ABSOLUTO de 'kw' en cualquier caso (de noche ambas convenciones dan 0 igual;
de día, cualquier lectura no nula se interpreta como generación real, sea
cual sea el signo con el que esté cableado ese reconectador específico).

Ventana de generación: fuera de HORA_INICIO_GENERACION-HORA_FIN_GENERACION,
la curva se fuerza a 0.0 sin importar qué haya reportado el reconectador --
una minigranja solar no genera de noche.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.services.mgs.solenium_client import SoleniumClient
from app.services.reporte_energia import historial
from app.services.reporte_energia.utils import HORAS_RECONECTADOR, HORAS_SOLARES, escalar_curva

HORAS = list(range(24))
HORA_INICIO_GENERACION = 5   # 5 am
HORA_FIN_GENERACION    = 18  # 6 pm (exclusiva -- la hora 17 sí cuenta, la 18 no)


def _potencia_kw(punto: dict) -> float:
    return abs(float(punto.get("kw") or 0))


def get_curva_reconectador(sol: SoleniumClient, id_solenium: int, fecha_str: str) -> pd.Series | None:
    """Curva horaria (kWh) del reconectador para un proyecto y fecha (YYYY-MM-DD).

    Retorna pd.Series[0..23] con NaN en las horas sin ningún punto real.
    Retorna None si el proyecto no tiene reconectador instalado, o si la
    consulta falla -- quien llama debe seguir con el flujo normal sin este
    relleno.
    """
    resp = sol.get_relay_historical(
        id_solenium, f"{fecha_str} 00:00:00", f"{fecha_str} 23:59:59", variables="kw",
    )
    puntos = resp.get("results") if isinstance(resp, dict) else None
    if not puntos:
        return None

    df = pd.DataFrame([
        {"time": ts, "kw": punto.get("kw")} for ts, punto in puntos.items()
    ])
    df["_t"] = pd.to_datetime(df["time"])
    df = df.sort_values("_t").reset_index(drop=True)

    acum = {h: 0.0 for h in HORAS}
    horas_con_dato = set(df["_t"].dt.hour)

    for i in range(len(df) - 1):
        hora = df.at[i, "_t"].hour
        p_kw = _potencia_kw(df.iloc[i])
        dt_h = (df.at[i + 1, "_t"] - df.at[i, "_t"]).total_seconds() / 3600
        acum[hora] += p_kw * dt_h

    if len(df) >= 2:
        hora = df.at[len(df) - 1, "_t"].hour
        p_kw = _potencia_kw(df.iloc[-1])
        dt_h = (df.at[len(df) - 1, "_t"] - df.at[len(df) - 2, "_t"]).total_seconds() / 3600
        acum[hora] += p_kw * dt_h

    curva = pd.Series(acum, dtype=float)
    for h in HORAS:
        if not (HORA_INICIO_GENERACION <= h < HORA_FIN_GENERACION):
            curva[h] = 0.0
        elif h not in horas_con_dato:
            curva[h] = None
    return curva


def rellenar_horas_faltantes(
    db: Session,
    sol: SoleniumClient,
    curva: pd.Series,
    id_solenium: int | None,
    fecha_str: str,
    frontera_id: int | None = None,
    curva_solenium: pd.Series | None = None,
    fp: float | None = None,
) -> tuple[pd.Series, set[int], set[int], set[int]]:
    """Rellena las horas en NaN de `curva` en tres pasos, en orden:

    1. Curva de Solenium (inversores) del MISMO día × factor de pérdida.
    2. Reconectador (dato físico directo del punto de generación).
    3. Histórico horario PROPIO de la frontera (último recurso) -- mediana
       del total diario × forma horaria típica de los últimos días
       confiables (ver historial.py).

    Las horas que ninguna de las tres fuentes cubre quedan en NaN -- no se
    inventa un valor. Cada fuente además solo se acepta dentro de su propia
    ventana horaria (HORAS_RECONECTADOR/HORAS_SOLARES en utils.py) -- fuera
    de esas horas la generación real ya se espera en ~0, así que rellenar
    ahí no protege nada y solo arriesga meter ruido de telemetría nocturna
    como si fuera dato real (ver MGS 0022 La Cumbia 2026-08-05).

    Retorna (curva_rellenada, horas_reconectador, horas_solenium, horas_historico).
    """
    horas_reconectador: set[int] = set()
    horas_solenium: set[int] = set()
    horas_historico: set[int] = set()

    if not curva.isna().any():
        return curva, horas_reconectador, horas_solenium, horas_historico

    curva = curva.copy()
    horas_faltantes = set(curva[curva.isna()].index)

    if curva_solenium is not None and fp is not None:
        for h in list(horas_faltantes):
            if h not in HORAS_SOLARES:
                continue
            valor_inv = curva_solenium.get(h) if isinstance(curva_solenium, pd.Series) else None
            if pd.notna(valor_inv):
                curva[h] = valor_inv * fp
                horas_solenium.add(h)
        horas_faltantes -= horas_solenium

    if horas_faltantes and id_solenium is not None:
        curva_relay = get_curva_reconectador(sol, int(id_solenium), fecha_str)
        if curva_relay is not None:
            for h in list(horas_faltantes):
                if h not in HORAS_RECONECTADOR:
                    continue
                valor = curva_relay.get(h)
                if pd.notna(valor):
                    curva[h] = valor
                    horas_reconectador.add(h)
            horas_faltantes -= horas_reconectador

    if horas_faltantes and frontera_id is not None:
        fecha = pd.to_datetime(fecha_str).date()
        mediana, _ = historial.get_mediana_generacion(db, frontera_id, fecha)
        if mediana is not None:
            forma, _ = historial.get_forma_generacion(db, frontera_id, fecha)
            if forma is not None:
                curva_historica = escalar_curva(forma, mediana)
                for h in list(horas_faltantes):
                    if h not in HORAS_SOLARES:
                        continue
                    curva[h] = curva_historica[h]
                    horas_historico.add(h)

    return curva, horas_reconectador, horas_solenium, horas_historico
