"""Clasificación energética mensual (categorías a-f) y su snapshot.

Puerto de `app/services/clasificacion_energia.py`. Fuente única: el resultado de
`plantas_contratos` (que a su vez resuelve GESCON). Este módulo NO reimplementa la
lógica de contratos — solo re-agrupa en las 6 categorías estandarizadas y
materializa el snapshot en `clasificacion_energia_mensual`.

  a. ppa_venta_ungg    ← contratos de venta, plantas NO duplicadas
  b. ppa_compra_ungc   ← compras de UNGC (GESCON puro)
  c. bolsa_compra_ungg ← plantas es_duplicado=True agrupadas por el contrato de
                         venta al que aportan + plantas uso_del_recurso=True
  d. bolsa_compra_ungc ← sin reglas definidas (siempre vacía, reservada)
  e. bolsa_venta_ungg  ← remanente sin SIC vigente ("bolsa_libre")
  f. bolsa_venta_ungc  ← remanente con SIC vigente comprador UNGC
  g. ppa_compra_externa← PPAs de compra directa a terceros SIN registro GESCON.
                         Solo piscina de vista: NO se materializa en el snapshot
                         a-f porque esas plantas están fuera del MEM.

El remanente e/f se calcula por DÍAS, no por plantas: una planta que salió de su
contrato a mitad de mes aporta un tramo a la bolsa y sigue listada en (a) con su
ventana. Por eso una misma planta puede tener varias filas en un mes.

**El ciclo de importación desapareció al portar.** En FastAPI este módulo
importaba `app.api.v1.cumplimiento.get_plantas_contratos` — un servicio llamando
a una vista, con `db=..., _=None` — y por eso el import estaba diferido dentro de
la función. Ahora llama a `plantas_contratos`, que es un servicio.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from django.db import transaction

from apps.mercado_xm.models import ClasificacionEnergiaMensual

CATEGORIAS_ENERGIA = [
    {
        "key": "ppa_venta_ungg", "letra": "a", "agente": "UNGG",
        "mercado": "ppa", "rol": "venta", "label": "PPA Venta (UNGG)",
        "descripcion": "Plantas en contratos GESCON donde UNGG le vende a otro "
                       "agente (Terpel, NEU, etc.). Incluye plantas en 'uso del "
                       "recurso' (cliente en bolsa; se le liquida a precio bolsa), "
                       "marcadas con uso_del_recurso=true.",
        "regla_pendiente": False,
    },
    {
        "key": "ppa_compra_ungc", "letra": "b", "agente": "UNGC",
        "mercado": "ppa", "rol": "compra", "label": "PPA Compra (UNGC)",
        "descripcion": "Contratos en que UNGC compra energía a algún agente en "
                       "GESCON (usualmente a UNGG).",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_compra_ungg", "letra": "c", "agente": "UNGG",
        "mercado": "bolsa", "rol": "compra", "label": "Compra en Bolsa (UNGG)",
        "descripcion": "Compras de UNGG a precio de bolsa. Hoy: plantas "
                       "duplicadas que aportan a un contrato con origen bolsa. "
                       "Incluye la compra interna de 'uso del recurso' "
                       "(uso_del_recurso=true): el vendedor es el cliente dueño "
                       "de la planta, no el mercado. Los contratos PLC entrarán "
                       "aquí cuando se liquiden en plataforma.",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_compra_ungc", "letra": "d", "agente": "UNGC",
        "mercado": "bolsa", "rol": "compra", "label": "Compra en Bolsa (UNGC)",
        "descripcion": "UNGC comprando en bolsa. Reglas de negocio aún por "
                       "definir: la categoría existe reservada, sin filas.",
        "regla_pendiente": True,
    },
    {
        "key": "bolsa_venta_ungg", "letra": "e", "agente": "UNGG",
        "mercado": "bolsa", "rol": "venta", "label": "Venta en Bolsa (UNGG)",
        "descripcion": "Plantas sin contrato vigente en GESCON: venden en bolsa "
                       "desde UNGG como generador.",
        "regla_pendiente": False,
    },
    {
        "key": "bolsa_venta_ungc", "letra": "f", "agente": "UNGC",
        "mercado": "bolsa", "rol": "venta", "label": "Venta en Bolsa (UNGC)",
        "descripcion": "UNGC le compra la energía a UNGG (usualmente a precio "
                       "de bolsa) para venderla en bolsa — SIC vigente con "
                       "comprador UNGC.",
        "regla_pendiente": False,
    },
]

CATEGORIAS_KEYS = {c["key"] for c in CATEGORIAS_ENERGIA}


# Momento en que cambió la LÓGICA de clasificación. El snapshot de un mes se
# materializa y se reutiliza, así que un mes ya calculado seguiría sirviendo
# filas viejas para siempre tras un cambio de reglas. Los snapshots anteriores a
# esta marca se recalculan solos la próxima vez que se consultan.
# Subir esta fecha al cambiar las reglas de derivación de piscinas.
#   2026-07-26 → la bolsa pasó a calcularse por días (historial intra-mes).
LOGICA_ACTUALIZADA_EN = datetime(2026, 7, 26, tzinfo=timezone.utc)


def snapshot_obsoleto(fila) -> bool:
    """True si la fila se calculó con una versión anterior de las reglas."""
    if fila is None or fila.calculado_en is None:
        return True
    calc = fila.calculado_en
    if calc.tzinfo is None:  # SQLite devuelve naive
        calc = calc.replace(tzinfo=timezone.utc)
    return calc < LOGICA_ACTUALIZADA_EN


def derivar_pools(data: dict) -> dict:
    """Re-agrupa el dict de plantas-contratos en las 6 piscinas.

    a/b/c son listas de CONTRATOS (cada uno con sus plantas); d/e/f son listas
    planas de PLANTAS. Devuelve {"pools": ..., "counts": {key: n_plantas}}.
    """
    a, c = [], []
    for ct in data.get("venta") or []:
        plantas = ct.get("plantas") or []
        dup = [p for p in plantas if p.get("es_duplicado")]
        ur = [p for p in plantas if p.get("uso_del_recurso")]
        # (a) lista TODAS las plantas del contrato — las duplicadas también
        # aportan a él y se muestran con su indicador (es_duplicado). En la
        # tabla/API estándar el duplicado clasifica solo en (c): ver
        # _filas_desde_pools, que las excluye de las filas de (a).
        a.append({**ct, "plantas": plantas})
        # (c) espejo: duplicados (compra real en bolsa) + uso del recurso (compra
        # interna al cliente a precio bolsa — esa planta TAMBIÉN clasifica en (a)).
        if dup or ur:
            c.append({**ct, "plantas": dup + ur})

    pools = {
        "ppa_venta_ungg": a,
        "ppa_compra_ungc": data.get("compra") or [],
        "bolsa_compra_ungg": c,
        "bolsa_compra_ungc": [],  # regla pendiente (catálogo: regla_pendiente)
        "bolsa_venta_ungg": data.get("bolsa_libre")
            or [p for p in (data.get("bolsa") or []) if p.get("piscina") != "comercializador"],
        "bolsa_venta_ungc": data.get("bolsa_comercializador")
            or [p for p in (data.get("bolsa") or []) if p.get("piscina") == "comercializador"],
        # (g) plantas externas: solo vista, no entra a _filas_desde_pools (fuera del MEM)
        "ppa_compra_externa": data.get("compra_externa") or [],
    }
    def _plantas(key, items):
        if key in ("ppa_venta_ungg", "ppa_compra_ungc", "bolsa_compra_ungg",
                   "ppa_compra_externa"):
            return [p for ct in items for p in (ct.get("plantas") or [])]
        return items

    # counts = TODAS las filas listadas (incluye el historial del mes: tramos que
    # ya terminaron). counts_vigentes = solo las que siguen vivas a la fecha de
    # corte — es lo que muestran los chips de la vista. `counts` conserva su
    # semántica original para no romper a los consumidores de la API.
    counts, counts_vigentes, counts_terminados = {}, {}, {}
    for key, items in pools.items():
        ps = _plantas(key, items)
        counts[key] = len(ps)
        # Sin `estado` (payloads viejos / llamadas directas) se asume vigente.
        counts_vigentes[key] = sum(1 for p in ps if p.get("estado", "vigente") == "vigente")
        counts_terminados[key] = sum(1 for p in ps if p.get("estado") == "terminado")
    return {
        "pools": pools,
        "counts": counts,
        "counts_vigentes": counts_vigentes,
        "counts_terminados": counts_terminados,
    }


def _filas_desde_pools(pools: dict, anio: int, mes: int) -> list[ClasificacionEnergiaMensual]:
    filas: list[ClasificacionEnergiaMensual] = []

    def _f(categoria, planta, contrato_id=None):
        return ClasificacionEnergiaMensual(
            anio=anio, mes=mes, categoria=categoria,
            proyecto_id=planta["id"],
            contrato_ppa_id=contrato_id,
            codigo_sic=planta.get("codigo_sic"),
            # Para los tramos de bolsa libre no hay registro SIC: la ventana real
            # es el propio tramo del mes (segmento_*).
            fecha_inicio=_iso(planta.get("fecha_inicio") or planta.get("segmento_inicio")),
            fecha_fin=_iso(planta.get("fecha_fin") or planta.get("segmento_fin")),
            uso_del_recurso=bool(planta.get("uso_del_recurso")),
        )

    for key in ("ppa_venta_ungg", "ppa_compra_ungc", "bolsa_compra_ungg"):
        for ct in pools[key]:
            # Las tarjetas GESCON-puras (compra UNGC) pueden traer id sintético
            # "gescon-<sic>"; el FK solo admite el id real del contrato PPA.
            cid = ct.get("contrato_ppa_id")
            if cid is None and isinstance(ct.get("id"), int):
                cid = ct["id"]
            for p in ct.get("plantas") or []:
                # En (a) los duplicados solo se MUESTRAN (badge); su fila
                # estándar vive en (c) — sin doble clasificación en BD/API.
                # EXCEPCIÓN deliberada: uso_del_recurso clasifica DOBLE (a+c):
                # la energía entra por contrato (a) y a la vez Unergy le compra
                # al cliente a precio bolsa (c). Son dos operaciones reales.
                if key == "ppa_venta_ungg" and p.get("es_duplicado"):
                    continue
                filas.append(_f(key, p, contrato_id=cid))
    for key in ("bolsa_venta_ungg", "bolsa_venta_ungc"):
        for p in pools[key]:
            filas.append(_f(key, p))
    return filas


def _iso(v):
    if not v:
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def recalcular_clasificacion(anio: int, mes: int) -> list[ClasificacionEnergiaMensual]:
    """Recalcula el snapshot del mes desde GESCON/PPA y lo persiste (borra+inserta
    el mes completo, en una transacción). Devuelve las filas nuevas."""
    from apps.mercado_xm.services.cumplimiento.piscinas import plantas_contratos

    data = plantas_contratos(anio, mes)
    pools = data["pools"] if "pools" in data else derivar_pools(data)["pools"]
    filas = _filas_desde_pools(pools, anio, mes)

    with transaction.atomic():
        ClasificacionEnergiaMensual.objects.filter(anio=anio, mes=mes).delete()
        ClasificacionEnergiaMensual.objects.bulk_create(filas)
    return filas
