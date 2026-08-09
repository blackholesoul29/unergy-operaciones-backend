"""Generación mensual promedio por proyecto.

**Por qué existe.** Cada vista que necesita "cuánto genera esta planta en un mes"
salía a la API de generación de Unergy, planta por planta. Eso es lento (minutos
para 70 proyectos), frágil (si esa API está caída no hay vista) y se repite en
cada consulta aunque el número casi no cambie. Acá se calcula **una vez** y se
persiste en `proyectos.gen_mensual_promedio_mwh`; después alcanza con leer la BD.

**Qué es el promedio.** MWh por mes, sobre los últimos `meses` meses **completos**
con datos suficientes. El mes en curso NO entra: está a medias y bajaría el
promedio sin motivo. Un mes con muchos días sin lectura tampoco entra (ver
`RATIO_DIAS_MINIMO`): mediría la caída del monitoreo, no la de la planta.

**Manual vs. API.** Una planta recién energizada no tiene histórico y su promedio
se carga a mano. `gen_promedio_origen` distingue los dos casos y el recálculo
respeta lo manual salvo que se pida `force`. Es el mismo patrón que
`fecha_comercializacion_editada_manual`.

El módulo se divide a propósito en dos capas:

- `promedio_mensual` y `agrupar_por_mes` — **puras**, sin red ni BD. Es donde
  vive la regla y es lo que prueban los tests.
- `recalcular` — orquesta: baja el histórico, llama a las puras y persiste.
"""
from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.proyectos import EstadoProyectoEnum, Proyecto, TipoProyectoEnum

# Un mes entra al promedio si tiene lecturas en al menos este ratio de sus días.
# 0.85 deja pasar un fin de semana perdido del monitoreo pero descarta el mes de
# arranque de una planta, que arrastraría el promedio hacia abajo.
RATIO_DIAS_MINIMO = 0.85

# Cuántos meses completos mirar hacia atrás por defecto. Seis cubre medio año de
# estacionalidad sin castigar a las plantas jóvenes.
MESES_POR_DEFECTO = 6

ORIGEN_API = "api"
ORIGEN_MANUAL = "manual"


# ── Núcleo puro ──────────────────────────────────────────────────────────────

def agrupar_por_mes(por_dia: dict[date, float]) -> dict[tuple[int, int], dict]:
    """`{fecha: kwh}` → `{(año, mes): {"kwh": total, "dias": n}}`."""
    meses: dict[tuple[int, int], dict] = {}
    for dia, kwh in por_dia.items():
        clave = (dia.year, dia.month)
        m = meses.setdefault(clave, {"kwh": 0.0, "dias": 0})
        m["kwh"] += float(kwh or 0)
        m["dias"] += 1
    return meses


def promedio_mensual(
    por_dia: dict[date, float],
    hoy: date,
    meses: int = MESES_POR_DEFECTO,
) -> dict:
    """Promedio en MWh/mes sobre los últimos `meses` meses completos con datos.

    Devuelve siempre la misma forma, también cuando no alcanza para calcular:
    `{"promedio_mwh": None, "meses": 0, "desde": None, "hasta": None,
      "descartados": [...], "motivo": "..."}`. Un `None` explícito es mejor que un
    cero: "no sé" y "genera cero" son cosas distintas.
    """
    vacio = {"promedio_mwh": None, "meses": 0, "desde": None, "hasta": None,
             "descartados": [], "motivo": None}
    if not por_dia:
        return {**vacio, "motivo": "sin lecturas en el histórico"}

    # El mes en curso queda fuera: está incompleto por definición.
    primer_dia_mes_actual = date(hoy.year, hoy.month, 1)
    agrupados = agrupar_por_mes(por_dia)

    completos, descartados = [], []
    for (anio, mes), datos in sorted(agrupados.items()):
        inicio = date(anio, mes, 1)
        if inicio >= primer_dia_mes_actual:
            descartados.append(f"{anio}-{mes:02d}: mes en curso")
            continue
        dias_mes = calendar.monthrange(anio, mes)[1]
        if datos["dias"] < dias_mes * RATIO_DIAS_MINIMO:
            descartados.append(
                f"{anio}-{mes:02d}: solo {datos['dias']} de {dias_mes} días con lecturas"
            )
            continue
        completos.append(((anio, mes), datos["kwh"]))

    if not completos:
        return {**vacio, "descartados": descartados,
                "motivo": "ningún mes completo con datos suficientes"}

    usados = completos[-meses:]
    total_kwh = sum(kwh for _, kwh in usados)
    (a0, m0), (a1, m1) = usados[0][0], usados[-1][0]
    return {
        "promedio_mwh": round(total_kwh / len(usados) / 1000.0, 3),
        "meses": len(usados),
        "desde": date(a0, m0, 1),
        "hasta": date(a1, m1, calendar.monthrange(a1, m1)[1]),
        "descartados": descartados,
        "motivo": None,
    }


def proyectos_objetivo(db: Session, proyecto_ids: list[int] | None = None) -> list[Proyecto]:
    """Los proyectos a los que tiene sentido calcularles el promedio.

    Mismo universo que Cumplimiento: en operación y no autoconsumo. Se incluyen
    los que no tienen `sub_project` — no se les puede calcular nada, pero deben
    aparecer en el reporte para saber cuáles hay que cargar a mano.
    """
    q = db.query(Proyecto).filter(
        Proyecto.deleted_at.is_(None),
        Proyecto.estado == EstadoProyectoEnum.en_operacion,
        Proyecto.tipo_proyecto != TipoProyectoEnum.autoconsumo,
    )
    if proyecto_ids:
        q = q.filter(Proyecto.id.in_(proyecto_ids))
    return q.order_by(Proyecto.nombre_comercial).all()


def aplicar(proyecto: Proyecto, resultado: dict, ahora: datetime) -> None:
    """Escribe el resultado del cálculo en el proyecto. Sin commit."""
    proyecto.gen_mensual_promedio_mwh = Decimal(str(resultado["promedio_mwh"]))
    proyecto.gen_promedio_origen = ORIGEN_API
    proyecto.gen_promedio_meses = resultado["meses"]
    proyecto.gen_promedio_desde = resultado["desde"]
    proyecto.gen_promedio_hasta = resultado["hasta"]
    proyecto.gen_promedio_actualizado_en = ahora


def decidir(proyecto: Proyecto, force: bool) -> str | None:
    """¿Hay que saltarse este proyecto? Devuelve el motivo, o None si se procesa."""
    if proyecto.gen_promedio_origen == ORIGEN_MANUAL and not force:
        return "valor manual (usar force=true para pisarlo)"
    if not (proyecto.sub_project or proyecto.alias_monitoreo):
        return "sin identificador de monitoreo: cargar el promedio a mano"
    return None


# ── Orquestación (red + BD) ──────────────────────────────────────────────────

async def recalcular(
    db: Session,
    meses: int = MESES_POR_DEFECTO,
    dry_run: bool = True,
    force: bool = False,
    proyecto_ids: list[int] | None = None,
    hoy: date | None = None,
) -> dict:
    """Recalcula el promedio desde la API de generación y lo persiste.

    `dry_run=True` (el default) reporta sin escribir. `force=True` pisa también
    los valores cargados a mano.

    Un proyecto que falla no tumba la corrida: queda en `fallidos` con su motivo.
    Nada de huecos callados — un proyecto que no se pudo calcular tiene que verse.
    """
    # Import local: monitoreo.py importa modelos y schemas pesados, y este módulo
    # lo consume también el arranque. Traerlo acá evita el ciclo.
    from app.api.v1.monitoreo import (_COL_TZ, _compute_deltas, _fetch_unergy_raw,
                                      _unergy_token)

    hoy = hoy or datetime.now(_COL_TZ).date()
    ahora = datetime.now(timezone.utc)
    objetivo = proyectos_objetivo(db, proyecto_ids)

    actualizados, sin_datos, saltados, fallidos = [], [], [], []

    a_procesar = []
    for p in objetivo:
        motivo = decidir(p, force)
        if motivo:
            saltados.append({"id": p.id, "nombre": p.nombre_comercial, "motivo": motivo})
        else:
            a_procesar.append(p)

    if a_procesar:
        try:
            token = await _unergy_token()
        except Exception as e:  # noqa: BLE001
            return {"error": f"no se pudo autenticar contra la API de generación: {e}",
                    "actualizados": [], "sin_datos": [], "saltados": saltados, "fallidos": []}

        # Ventana: `meses` completos hacia atrás + el mes en curso (que se descarta
        # después, pero pedirlo evita un borde raro si la corrida cae el día 1).
        inicio = date(hoy.year, hoy.month, 1) - timedelta(days=31 * (meses + 1))
        d_from = datetime(inicio.year, inicio.month, 1, 0, 0, 0, tzinfo=_COL_TZ)
        d_to = datetime(hoy.year, hoy.month, hoy.day, 23, 59, 59, tzinfo=_COL_TZ)
        # Se pide dos días antes para tener la lectura previa: el contador es
        # acumulado y el primer delta necesita con qué restarse.
        fetch_from = (d_from - timedelta(days=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fetch_to = d_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        sem = asyncio.Semaphore(8)   # mismo orden de paralelismo que el resto del módulo

        async def uno(p: Proyecto):
            sub = p.sub_project or p.alias_monitoreo
            async with sem:
                try:
                    lecturas = await _fetch_unergy_raw(token, sub, fetch_from, fetch_to, verified_only=True)
                    if not lecturas:
                        lecturas = await _fetch_unergy_raw(token, sub, fetch_from, fetch_to, verified_only=False)
                    return p, _compute_deltas(lecturas, d_from, d_to), None
                except Exception as e:  # noqa: BLE001
                    return p, None, str(e)

        for item in await asyncio.gather(*[uno(p) for p in a_procesar], return_exceptions=True):
            if isinstance(item, BaseException):
                fallidos.append({"id": None, "nombre": None, "error": str(item)})
                continue
            p, entradas, error = item
            if error is not None:
                fallidos.append({"id": p.id, "nombre": p.nombre_comercial, "error": error})
                continue

            por_dia: dict[date, float] = {}
            for e in entradas or []:
                try:
                    d = date.fromisoformat(str(e.get("date"))[:10])
                except (TypeError, ValueError):
                    continue
                por_dia[d] = por_dia.get(d, 0.0) + float(e.get("kwh") or 0)

            r = promedio_mensual(por_dia, hoy=hoy, meses=meses)
            if r["promedio_mwh"] is None:
                sin_datos.append({"id": p.id, "nombre": p.nombre_comercial,
                                  "motivo": r["motivo"], "descartados": r["descartados"][:4]})
                continue

            anterior = float(p.gen_mensual_promedio_mwh) if p.gen_mensual_promedio_mwh is not None else None
            if not dry_run:
                aplicar(p, r, ahora)
            actualizados.append({
                "id": p.id, "nombre": p.nombre_comercial,
                "anterior_mwh": anterior, "nuevo_mwh": r["promedio_mwh"],
                "meses": r["meses"],
                "desde": r["desde"].isoformat(), "hasta": r["hasta"].isoformat(),
            })

        if not dry_run:
            db.commit()

    return {
        "dry_run": dry_run,
        "force": force,
        "meses_pedidos": meses,
        "hoy": hoy.isoformat(),
        "n_objetivo": len(objetivo),
        "n_actualizados": len(actualizados),
        "n_sin_datos": len(sin_datos),
        "n_saltados": len(saltados),
        "n_fallidos": len(fallidos),
        "actualizados": actualizados,
        # Estas tres listas son el valor del reporte: dicen exactamente qué
        # plantas hay que cargar a mano y cuáles hay que mirar.
        "sin_datos": sin_datos,
        "saltados": saltados,
        "fallidos": fallidos,
    }
