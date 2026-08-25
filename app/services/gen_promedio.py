"""Generación mensual promedio por proyecto.

**Por qué existe.** Cada vista que necesita "cuánto genera esta planta en un mes"
salía a la API de generación de Unergy, planta por planta. Eso es lento (minutos
para 70 proyectos), frágil (si esa API está caída no hay vista) y se repite en
cada consulta aunque el número casi no cambie. Acá se calcula **una vez** y se
persiste en `proyectos.gen_mensual_promedio_mwh`; después alcanza con leer la BD.

**Qué es el promedio.** MWh en un mes típico, medido sobre una ventana **móvil**
de los últimos 30 días corridos — no sobre el mes calendario anterior. Un
promedio "de julio" consultado el 9 de agosto describe algo que terminó hace más
de una semana; los últimos 30 días describen la planta hoy.

El día de hoy no entra: está a medias. Y si la ventana tiene muchos días sin
lectura (ver `RATIO_DIAS_MINIMO`) no se devuelve número: sería medir la caída del
monitoreo, no la de la planta.

**Manual vs. API.** Una planta recién energizada no tiene histórico y su promedio
se carga a mano. `gen_promedio_origen` distingue los dos casos y el recálculo
respeta lo manual salvo que se pida `force`. Es el mismo patrón que
`fecha_comercializacion_editada_manual`.

El módulo se divide a propósito en dos capas:

- `promedio_mensual` y `decidir` — **puras**, sin red ni BD. Ahí vive la regla
  y es lo que prueban los tests.
- `recalcular` — orquesta: baja el histórico, llama a las puras y persiste.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.proyectos import EstadoProyectoEnum, Proyecto, TipoProyectoEnum

# La ventana vale si al menos este ratio de sus días tiene lectura. 0.85 deja
# pasar un fin de semana perdido del monitoreo pero descarta una planta recién
# energizada, que daría un promedio construido sobre cuatro días.
RATIO_DIAS_MINIMO = 0.85

# Largo de la ventana móvil, en días corridos hacia atrás desde ayer. 30 ≈ un mes
# y es lo que hace que el número describa a la planta HOY y no el mes pasado.
DIAS_POR_DEFECTO = 30

# El campo se expresa siempre como "MWh en un mes de 30 días", sea cual sea el
# largo de la ventana: si no, cambiar `dias` cambiaría la unidad del dato.
DIAS_MES_REFERENCIA = 30

ORIGEN_API = "api"
ORIGEN_MANUAL = "manual"


# ── Núcleo puro ──────────────────────────────────────────────────────────────

def promedio_mensual(
    por_dia: dict[date, float],
    hoy: date,
    dias: int = DIAS_POR_DEFECTO,
) -> dict:
    """Promedio en MWh/mes sobre los últimos `dias` días corridos.

    La ventana es `[hoy - dias, hoy - 1]`: **hoy no entra** porque está a medias,
    y lo anterior a la ventana tampoco, aunque haya histórico. Esa es la
    diferencia con promediar el mes calendario pasado — el número describe a la
    planta ahora.

    El promedio se normaliza por los días **con lectura**, no por el largo de la
    ventana: si el monitoreo se cayó tres días, la planta no generó menos, y
    dividir por 30 haría ver una caída que no existe.

    Devuelve siempre la misma forma, también cuando no alcanza para calcular:
    `promedio_mwh=None` con el motivo. Un `None` explícito es mejor que un cero —
    "no sé" y "genera cero" son cosas distintas.
    """
    hasta = hoy - timedelta(days=1)
    desde = hoy - timedelta(days=dias)
    vacio = {"promedio_mwh": None, "dias": dias, "dias_con_datos": 0,
             "desde": desde, "hasta": hasta, "motivo": None}

    en_ventana = {d: float(k or 0) for d, k in por_dia.items() if desde <= d <= hasta}
    if not en_ventana:
        return {**vacio, "motivo": f"sin lecturas entre {desde} y {hasta}"}

    n = len(en_ventana)
    if n < dias * RATIO_DIAS_MINIMO:
        return {**vacio, "dias_con_datos": n,
                "motivo": f"solo {n} de {dias} días con lecturas: "
                          "muy poco para un promedio confiable"}

    promedio_diario = sum(en_ventana.values()) / n
    return {
        "promedio_mwh": round(promedio_diario * DIAS_MES_REFERENCIA / 1000.0, 3),
        "dias": dias,
        "dias_con_datos": n,
        "desde": desde,
        "hasta": hasta,
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
        # `!= autoconsumo` a secas deja fuera los NULL: en SQL una comparación
        # contra NULL da NULL, y NULL no pasa el WHERE. Con eso, toda planta sin
        # tipo cargado quedaba fuera del recálculo en silencio y nunca recibía
        # promedio, se corriera las veces que se corriera.
        or_(Proyecto.tipo_proyecto.is_(None),
            Proyecto.tipo_proyecto != TipoProyectoEnum.autoconsumo),
    )
    if proyecto_ids:
        q = q.filter(Proyecto.id.in_(proyecto_ids))
    return q.order_by(Proyecto.nombre_comercial).all()


def aplicar(proyecto: Proyecto, resultado: dict, ahora: datetime) -> None:
    """Escribe el resultado del cálculo en el proyecto. Sin commit."""
    proyecto.gen_mensual_promedio_mwh = Decimal(str(resultado["promedio_mwh"]))
    proyecto.gen_promedio_origen = ORIGEN_API
    proyecto.gen_promedio_dias = resultado["dias_con_datos"]
    proyecto.gen_promedio_desde = resultado["desde"]
    proyecto.gen_promedio_hasta = resultado["hasta"]
    proyecto.gen_promedio_actualizado_en = ahora


def decidir(proyecto: Proyecto, force: bool) -> str | None:
    """¿Hay que saltarse este proyecto? Devuelve el motivo, o None si se procesa."""
    if proyecto.gen_promedio_origen == ORIGEN_MANUAL and not force:
        return "valor manual (usar force=true para pisarlo)"
    if not proyecto.sub_project:
        return "sin identificador de monitoreo: cargar el promedio a mano"
    return None


# ── Orquestación (red + BD) ──────────────────────────────────────────────────

async def recalcular(
    db: Session,
    dias: int = DIAS_POR_DEFECTO,
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

        # Se pide la ventana con dos días de colchón: el primer delta necesita una
        # lectura previa con la que restarse (el contador es acumulado).
        inicio = hoy - timedelta(days=dias + 2)
        d_from = datetime(inicio.year, inicio.month, inicio.day, 0, 0, 0, tzinfo=_COL_TZ)
        d_to = datetime(hoy.year, hoy.month, hoy.day, 23, 59, 59, tzinfo=_COL_TZ)
        fetch_from = (d_from - timedelta(days=2)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fetch_to = d_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        sem = asyncio.Semaphore(8)   # mismo orden de paralelismo que el resto del módulo

        async def uno(p: Proyecto):
            sub = p.sub_project
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

            r = promedio_mensual(por_dia, hoy=hoy, dias=dias)
            if r["promedio_mwh"] is None:
                sin_datos.append({"id": p.id, "nombre": p.nombre_comercial,
                                  "motivo": r["motivo"], "dias_con_datos": r["dias_con_datos"]})
                continue

            anterior = float(p.gen_mensual_promedio_mwh) if p.gen_mensual_promedio_mwh is not None else None
            if not dry_run:
                aplicar(p, r, ahora)
            actualizados.append({
                "id": p.id, "nombre": p.nombre_comercial,
                "anterior_mwh": anterior, "nuevo_mwh": r["promedio_mwh"],
                "dias_con_datos": r["dias_con_datos"],
                "desde": r["desde"].isoformat(), "hasta": r["hasta"].isoformat(),
            })

        if not dry_run:
            db.commit()

    return {
        "dry_run": dry_run,
        "force": force,
        "dias_ventana": dias,
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
