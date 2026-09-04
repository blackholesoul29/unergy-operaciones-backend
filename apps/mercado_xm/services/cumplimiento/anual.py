"""Los doce meses de un contrato: prorrateo, proyección y sets de descarga.

Copiado SIN CAMBIOS de `app/api/v1/cumplimiento.py`. `_anual_meses_para_contrato`
recibe TODO precargado (los cachés de generación, el mapa GESCON por mes, los
compromisos) y no consulta nada: por eso se pudo mover verbatim aunque sean 231
líneas. Quien la llama es responsable de llenar esos cachés — ver
`_build_fetch_sets`, que decide qué meses hay que pedirle a la API antes de
entrar al bucle.

El mes en curso se PROYECTA (promedio de los últimos días × días restantes); los
cerrados se leen. Confundir los dos es lo que hacía que la matriz anual mostrara
un cumplimiento falso a mitad de mes.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from apps.mercado_xm.services.cumplimiento.periodos import (
    _gen_vigencia_mwh, _vigencia_window,
)

def _anual_meses_para_contrato(contrato, year, gescon_per_month, comp_map, month_cache, avg_cache, today, range_cache=None):
    """Construye los 12 meses + desglose por proyecto para un contrato.

    Caches (month_cache/avg_cache/range_cache), gescon_per_month y comp_map vienen
    ya poblados (sin I/O aquí). Retorna (meses, proyectos) con `valor_mwh` por mes
    tanto a nivel de contrato como por proyecto, manteniendo:
    contrato.valor_mwh == Σ proyectos.valor_mwh.

    range_cache: dict[(sub_project, eff_start, eff_end)] -> {"mwh": ...} con la
    generación REAL sumada día a día para un registro que estuvo vigente solo
    PARTE de un mes (relevo, arranque o terminación a mitad de mes). Cuando el
    registro cubre el mes completo se sigue usando month_cache (sin cambios).
    """
    range_cache = range_cache or {}
    # proyectos_acc: (pid, sp, nombre) -> {"pct": last_pct, "meses": [valor_mwh x 12]}
    proyectos_acc: dict = {}

    meses = []
    for m in range(1, 13):
        total_dias = calendar.monthrange(year, m)[1]
        first_day_m = date(year, m, 1)
        last_day_m = date(year, m, total_dias)
        is_current = (year == today.year and m == today.month)
        is_future = (year > today.year) or (year == today.year and m > today.month)
        dia_actual = today.day if is_current else total_dias

        # Vigencia del contrato en el mes: un compromiso del mes M solo cuenta si el
        # contrato está vigente en M. Respeta fecha_inicio y fecha_fin del PPAContrato.
        # Caso real: Naos 2/3 terminaron el 30-abr-2026 (se acabó la representación de
        # las plantas); sus compromisos de may-dic NO deben contar ni marcar déficit.
        c_ini = getattr(contrato, "fecha_inicio", None)
        c_fin = getattr(contrato, "fecha_fin", None)
        vigente_m = (
            (c_ini is None or c_ini <= last_day_m)
            and (c_fin is None or c_fin >= first_day_m)
        )

        comp = comp_map.get(m)
        min_mwh: Optional[float] = float(comp.energia_minima) if comp and comp.energia_minima is not None else None
        max_mwh: Optional[float] = float(comp.energia_maxima) if comp and comp.energia_maxima is not None else None
        plantas_esp: Optional[int] = int(comp.cantidad_proyectos) if comp and comp.cantidad_proyectos is not None else None

        plantas_mes = []
        gen_total = 0.0
        bolsa_dup_total = 0.0
        for asic in gescon_per_month[m]:
            proyecto = asic.proyecto
            nombre = proyecto.nombre_comercial if proyecto else f"Proyecto {asic.proyecto_id}"
            sp = proyecto.sub_project if proyecto else None
            pid = asic.proyecto_id
            pct = float(asic.porcentaje_despacho or 0)
            is_dup = bool(asic.es_duplicado)

            eff_start, eff_end = _vigencia_window(asic.fecha_inicio, asic.fecha_fin, first_day_m, last_day_m)
            dias_activos = max(0, (eff_end - eff_start).days + 1)
            proration = dias_activos / total_dias

            if sp:
                if is_future:
                    # Mes futuro sin datos reales: se sigue proyectando con el
                    # promedio diario reciente × días vigentes (avg × dias_activos).
                    avg = avg_cache.get(sp)
                    gp: Optional[float] = round(avg * total_dias, 3) if avg is not None else None
                    gen_contrato = round(gp * pct * proration, 3) if gp is not None else None
                else:
                    # Mes pasado/actual: generación REAL de la vigencia — total del
                    # mes si cubre el mes completo, o suma real de los días exactos
                    # si la vigencia fue parcial (helper compartido con Estrategia y
                    # Energía transada; nunca regla de tres sobre el total).
                    month_gen = month_cache.get((m, sp), {}).get("mwh")
                    range_gen = range_cache.get((sp, eff_start, eff_end), {}).get("mwh")
                    gp = _gen_vigencia_mwh(eff_start, eff_end, total_dias, month_gen, range_gen)
                    gen_contrato = round(gp * pct, 3) if gp is not None else None
            else:
                gp = None
                gen_contrato = None
            if gen_contrato is not None:
                # Cuenta para el cumplimiento sin importar el origen; el duplicado
                # se registra además en bolsa_dup_total como sub-cifra (origen bolsa).
                gen_total += gen_contrato
                if is_dup:
                    bolsa_dup_total += gen_contrato
            plantas_mes.append({
                "nombre": nombre,
                "sub_project": sp,
                "pct_despacho": pct,
                "dias_en_contrato": dias_activos,
                "dias_mes": total_dias,
                "gen_planta_mwh": gp,
                "gen_contrato_mwh": gen_contrato,
                "es_duplicado": is_dup,
                # getattr: los tests de endpoints usan fakes sin el atributo nuevo
                "uso_del_recurso": bool(getattr(asic, "uso_del_recurso", False)),
            })

            # Accumulate per-project valor_mwh (preliminary: gen_contrato for past/future)
            key = (pid, sp or "", nombre)
            if key not in proyectos_acc:
                proyectos_acc[key] = {"pct": pct, "is_dup": is_dup,
                                      "is_ur": bool(getattr(asic, "uso_del_recurso", False)),
                                      "meses": [None] * 12}
            proyectos_acc[key]["pct"] = pct  # last seen
            proyectos_acc[key]["meses"][m - 1] = gen_contrato  # will be overwritten for current month below

        gen_total = round(gen_total, 3)
        bolsa_dup_total = round(bolsa_dup_total, 3)

        # Projection based on 30-day rolling average
        gen_cierre: Optional[float] = None
        if is_current:
            dias_restantes = total_dias - dia_actual
            avg_30d_total = 0.0
            avg_available = False
            for asic in gescon_per_month[m]:
                proyecto = asic.proyecto
                sp = proyecto.sub_project if proyecto else None
                if not sp:
                    continue
                nombre = proyecto.nombre_comercial if proyecto else f"Proyecto {asic.proyecto_id}"
                pid = asic.proyecto_id
                pct = float(asic.porcentaje_despacho or 0)
                is_dup = bool(asic.es_duplicado)
                # La proyección incluye duplicados: la compra en bolsa también
                # cubre el contrato de cara a la contraparte.
                eff_start = max(first_day_m, asic.fecha_inicio) if asic.fecha_inicio else first_day_m
                eff_end = min(last_day_m, asic.fecha_fin) if asic.fecha_fin else last_day_m
                dias_activos = max(0, (eff_end - eff_start).days + 1)
                proration = dias_activos / total_dias
                avg_daily = avg_cache.get(sp)
                if avg_daily is not None:
                    avg_30d_total += avg_daily * pct * proration
                    avg_available = True

                # Per-project valor_mwh for current month = gen_contrato_actual + projection
                key = (pid, sp, nombre)
                gen_contrato_actual = proyectos_acc.get(key, {}).get("meses", [None] * 12)[m - 1] or 0.0
                if avg_daily is not None:
                    proj_planta = gen_contrato_actual + avg_daily * pct * proration * dias_restantes
                    if key in proyectos_acc:
                        proyectos_acc[key]["meses"][m - 1] = round(proj_planta, 3)
                # If avg_daily is None, leave gen_contrato as best estimate (already set)

            if avg_available and gen_total >= 0:
                gen_cierre = round(gen_total + avg_30d_total * dias_restantes, 3)
            gen_proy = gen_cierre
        elif is_future:
            gen_proy = gen_total if gen_total > 0 else None
        else:
            gen_proy = None

        # Contract-level valor_mwh: real → gen_total; current → gen_cierre; future → gen_proy
        if is_current and gen_cierre is not None:
            valor_mwh_contrato = gen_cierre
        elif is_future:
            valor_mwh_contrato = gen_proy if gen_proy is not None else gen_total
        else:
            valor_mwh_contrato = gen_total

        val = gen_cierre if is_current and gen_cierre is not None else (gen_proy if is_future else gen_total)
        if not vigente_m:
            # Contrato no vigente este mes: terminó (posterior a fecha_fin) o aún no
            # inicia (anterior a fecha_inicio). No hay compromiso que cumplir → no contar
            # ni marcar déficit. Se anula min/max/plantas y se marca el estado para que
            # el front muestre "finalizado"/"no_iniciado" en vez de 0 plantas / déficit.
            min_mwh = None
            max_mwh = None
            plantas_esp = None
            valor_mwh_contrato = None
            estado = "finalizado" if (c_fin and c_fin < first_day_m) else "no_iniciado"
            compras, excedentes = None, None
        elif min_mwh is not None or max_mwh is not None:
            if val is None:
                # Hay compromiso pero aún no hay generación/proyección (p.ej. mes futuro
                # sin plantas asignadas todavía): no se puede evaluar cumplimiento.
                estado, compras, excedentes = "sin_datos", None, None
            else:
                effective_min = min_mwh if min_mwh is not None else 0.0
                effective_max = max_mwh if max_mwh is not None else float('inf')
                if val < effective_min:
                    estado, compras, excedentes = "deficit", round(max(0., effective_min - val), 3), 0.
                elif val > effective_max:
                    estado, compras, excedentes = "excedente", 0., round(max(0., val - effective_max), 3)
                else:
                    estado, compras, excedentes = "ok", 0., 0.
        else:
            estado, compras, excedentes = "sin_compromisos", None, None

        tipo = "proyeccion_historica" if is_future else ("mes_actual" if is_current else "real")
        meses.append({
            "month": m,
            "gen_mwh": gen_total,
            "gen_proyectada_mwh": gen_proy,
            "gen_proyectada_cierre": gen_cierre,
            "min_mwh": min_mwh,
            "max_mwh": max_mwh,
            "estado": estado,
            "tipo_datos": tipo,
            "dia_actual": dia_actual if is_current else None,
            "dias_restantes": (total_dias - dia_actual) if is_current else None,
            "compras_bolsa_mwh": compras,
            "excedentes_bolsa_mwh": excedentes,
            "exposicion_bolsa_duplicados_mwh": bolsa_dup_total if bolsa_dup_total > 0 else None,
            "plantas": plantas_mes,
            "n_plantas": len(plantas_mes),
            # Cumplimiento de plantas: registradas (n_plantas) vs esperadas para el mes.
            # plantas_esp se anula en meses no vigentes (finalizado/no_iniciado).
            "plantas_esperadas": plantas_esp,
            "valor_mwh": valor_mwh_contrato,
        })

    # Build proyectos list
    proyectos = []
    for (pid, sp, nombre), acc in proyectos_acc.items():
        proy_meses = []
        for idx in range(12):
            proy_meses.append({
                "month": idx + 1,
                "valor_mwh": acc["meses"][idx],
                "pct_despacho": acc["pct"],
                "es_duplicado": acc["is_dup"],
                "uso_del_recurso": acc.get("is_ur", False),
            })
        proyectos.append({
            "id": pid,
            "nombre": nombre,
            "sub_project": sp,
            "pct_despacho_rep": acc["pct"],
            "meses": proy_meses,
        })

    return meses, proyectos

def _build_fetch_sets(gpm_por_contrato: dict, year: int, today) -> tuple:
    """Construye sets deduplicados de fetches a Unergy para todos los contratos.

    Replica la lógica de detección need_month/need_avg de get_anual pero sobre TODOS los
    contratos, devolviendo sets deduplicados:
      - need_month: set de (month, sub_project) para meses pasados/actuales
      - need_avg: set de sub_project para mes actual/futuros (proyección rolling avg)
      - need_range: set de (sub_project, eff_start, eff_end) para registros que
        estuvieron vigentes solo PARTE de un mes (pasado/actual) — su energía se
        calcula sumando los días reales, no prorrateando el total del mes.

    Clave: tuple order es (m, sp) igual que get_anual y month_cache[(m, sp)].
    """
    need_month: set = set()
    need_avg: set = set()
    need_range: set = set()
    for gpm in gpm_por_contrato.values():
        for m in range(1, 13):
            total_dias = calendar.monthrange(year, m)[1]
            first_day_m = date(year, m, 1)
            last_day_m = date(year, m, total_dias)
            is_current = (year == today.year and m == today.month)
            is_future = (year > today.year) or (year == today.year and m > today.month)
            for asic in gpm[m]:
                sp = asic.proyecto.sub_project if asic.proyecto else None
                if not sp:
                    continue
                if is_future:
                    need_avg.add(sp)
                    continue
                if is_current:
                    need_avg.add(sp)
                eff_start = max(first_day_m, asic.fecha_inicio) if asic.fecha_inicio else first_day_m
                eff_end = min(last_day_m, asic.fecha_fin) if asic.fecha_fin else last_day_m
                dias_activos = max(0, (eff_end - eff_start).days + 1)
                if 0 < dias_activos < total_dias:
                    need_range.add((sp, eff_start, eff_end))
                else:
                    need_month.add((m, sp))
    return need_month, need_avg, need_range
