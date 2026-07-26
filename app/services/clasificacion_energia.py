"""Derivación y persistencia de la clasificación energética mensual (a-f).

Fuente única: el resultado de `/cumplimiento/plantas-contratos` (que a su vez
resuelve GESCON vía `_resolve_gescon`). Este módulo NO reimplementa la lógica
de contratos — solo re-agrupa en las 6 categorías estandarizadas del catálogo
`CATEGORIAS_ENERGIA` y materializa el snapshot en BD.

Mapeo:
  a. ppa_venta_ungg   ← contratos de venta, plantas NO duplicadas
  b. ppa_compra_ungc  ← contratos de compra (tipo_contrato='compra')
  c. bolsa_compra_ungg← plantas es_duplicado=True agrupadas por el contrato de
                        venta al que aportan (origen bolsa). PLC: pendiente.
                        + plantas uso_del_recurso=True: compra interna al
                        cliente a precio bolsa (también clasifican en (a)).
  d. bolsa_compra_ungc← sin reglas definidas (siempre vacía, reservada)
  e. bolsa_venta_ungg ← remanente sin SIC vigente ("bolsa_libre")
  f. bolsa_venta_ungc ← remanente con SIC vigente comprador UNGC
                        ("bolsa_comercializador")

El remanente e/f se calcula por DÍAS, no por plantas: una planta que salió de su
contrato a mitad de mes aporta un tramo a la bolsa y sigue listada en (a) con su
ventana. Por eso una misma planta puede tener varias filas en un mes.
  g. ppa_compra_externa ← PPAs de compra directa a terceros SIN registro GESCON
                        (plantas externas, "compra_externa"). Solo piscina de
                        vista: NO se materializa en el snapshot a-f de BD porque
                        esas plantas están fuera del MEM.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.models.clasificacion_energia import ClasificacionEnergiaMensual


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


def recalcular_clasificacion(db: Session, anio: int, mes: int) -> list[ClasificacionEnergiaMensual]:
    """Recalcula el snapshot del mes desde GESCON/PPA y lo persiste
    (borra+inserta el mes completo, transaccional). Devuelve las filas nuevas."""
    # Import diferido para evitar ciclo (cumplimiento importa derivar_pools).
    from app.api.v1.cumplimiento import get_plantas_contratos

    data = get_plantas_contratos(year=anio, month=mes, db=db, _=None)
    pools = data["pools"] if "pools" in data else derivar_pools(data)["pools"]
    filas = _filas_desde_pools(pools, anio, mes)

    db.query(ClasificacionEnergiaMensual).filter(
        ClasificacionEnergiaMensual.anio == anio,
        ClasificacionEnergiaMensual.mes == mes,
    ).delete(synchronize_session=False)
    db.add_all(filas)
    db.commit()
    return filas
