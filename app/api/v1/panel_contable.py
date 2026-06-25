"""
Panel Contable — preliquidaciones y liquidaciones oficiales a partir de los
Estados de Resultados (ER) por proyecto.

Flujo:
  - cargar-er: recalcula con LibreOffice, parsea, matchea proyecto, divide por
    % del backend y guarda un PanelContable + líneas (borrador editable).
  - list: paneles del período con sus líneas por inversionista.
  - patch: actualizar flags/consecutivos del panel o editar una línea.
  - diferencia: cruza preliquidación vs oficial.
"""
import calendar
import logging
import os
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Usuario
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.clientes import Cliente
import json

from app.models.panel_contable import (
    PanelContable, PanelContableLinea, ClasificacionLiquidacion, MapeoCeldaConcepto,
    AliasFuenteIngreso,
)
from app.utils.er_loader import (
    recalcular_er, parsear_er, match_proyecto, extraer_proyecto_de_archivo,
    normalizar, leer_celda, _norm as _norm_concepto, _aplicar_signo, IVA, FEE_ADMIN,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panel-contable", tags=["Panel Contable"])


def _require_write(current: Usuario = Depends(get_current_user)):
    if current.rol.value not in ("admin", "liquidaciones"):
        raise HTTPException(403, "Se requiere rol admin o liquidaciones")
    return current


def _es_minigranja_operativa():
    """
    Filtro SQLAlchemy: el Panel Contable es SOLO de minigranjas operativas.
    Excluye AMC, Acanto, COLxxx, proyectos en desarrollo, etc.
    """
    return (Proyecto.tipo_proyecto == "minigranja") & (Proyecto.estado == "en_operacion")


# ── Schemas ──────────────────────────────────────────────────────────────────

class LineaPatch(BaseModel):
    id: int
    valor_cop: float | None = None
    comprobante_contable: str | None = None
    concepto: str | None = None


class PanelPatch(BaseModel):
    liquidar: bool | None = None
    liquidar_ingresos: bool | None = None
    liquidar_costos: bool | None = None
    generar_mandatos: bool | None = None
    fecha_firma: date | None = None
    consecutivo_ingresos: int | None = None
    consecutivo_costos: int | None = None
    lineas: list[LineaPatch] | None = None


class ReasignarConsecutivos(BaseModel):
    periodo: str
    tipo: str = "preliquidacion"
    consecutivo_ingresos_inicial: int
    consecutivo_costos_inicial: int
    # solo_faltantes=True: NO renumera todo; solo rellena los consecutivos que están
    # en None (preservando los ya asignados / editados a mano). Se usa al cargar la
    # vista para que todo panel marcado quede numerado sin pisar ediciones manuales.
    # solo_faltantes=False (default): renumeración completa desde el valor inicial.
    solo_faltantes: bool = False


class RedividirBody(BaseModel):
    periodo: str
    tipo: str = "preliquidacion"
    proyecto_id: int | None = None
    # forzar=True re-divide aun si los % parecen correctos (pisa ediciones manuales).
    forzar: bool = False


class AsignacionClasif(BaseModel):
    proyecto_id: int
    tipo: str  # 'normal' | 'neu' | 'nitro'


class ClasificacionBody(BaseModel):
    periodo: str
    asignaciones: list[AsignacionClasif]


class MapeoCeldaBody(BaseModel):
    proyecto_id: int
    periodo: str
    tipo: str = "preliquidacion"
    concepto: str
    hoja: str
    celda: str


class AliasFuenteBody(BaseModel):
    proyecto_id: int
    periodo: str
    tipo: str = "preliquidacion"
    columna_origen: str          # "Sheet1!G35" (celda de origen de la fuente)
    etiqueta: str                # nombre que pone la usuaria, ej "Ingreso Bruto Terpel 1"
    orden: int | None = None


class FuenteIngresoBody(BaseModel):
    proyecto_id: int
    periodo: str
    tipo: str = "preliquidacion"
    etiqueta: str
    hoja: str
    celda: str
    orden: int | None = None


class FuenteIngresoDeleteBody(BaseModel):
    proyecto_id: int
    periodo: str
    tipo: str = "preliquidacion"
    columna_origen: str          # "Sheet1!G35" — identifica la fuente a quitar


# ── Construcción de líneas a partir del ER parseado ────────────────────────────

def _construir_lineas_base(parsed: dict) -> list[dict]:
    """
    Renglones del ER al 100% (sin dividir). Cada uno: {grupo, concepto, valor,
    hoja, celda}. hoja/celda = la celda del ER de donde salió el valor (PROPONER);
    el frontend la muestra y la usuaria puede corregirla. Los totales y la utilidad
    los calcula el frontend; aquí solo van renglones base.
    """
    lineas: list[dict] = []
    tipo = (parsed.get("tipo") or "normal").lower()

    def _orig(d: dict) -> dict:
        return {"hoja": d.get("hoja"), "celda": d.get("celda")}

    # INGRESOS. Para NEU/NITRO los conceptos vienen ya desglosados desde el parser
    # (sección "Ingresos y costos"). Para normal se conserva el formato histórico
    # con el comercializador en la etiqueta del ingreso bruto.
    if tipo in ("neu", "nitro"):
        for d in parsed.get("ingresos_detalle", []):
            lineas.append({"grupo": "ingresos", "concepto": d["concepto"], "valor": d["valor"], **_orig(d)})
    else:
        com = parsed.get("comercializador") or ""
        etiqueta_ing = f"Ingreso Bruto{(' ' + com) if com else ''}".strip()
        ib = next((d for d in parsed.get("ingresos_detalle", [])
                   if "bruto" in (d["concepto"].lower())), {})
        lineas.append({"grupo": "ingresos", "concepto": etiqueta_ing,
                       "valor": parsed["ingreso_bruto"], **_orig(ib)})
        if parsed.get("tiene_bolsa"):
            if parsed.get("venta_bolsa"):
                vb = next((d for d in parsed.get("ingresos_detalle", [])
                           if "venta" in d["concepto"].lower() and "bolsa" in d["concepto"].lower()), {})
                lineas.append({"grupo": "ingresos", "concepto": "Venta en bolsa", "valor": parsed["venta_bolsa"], **_orig(vb)})
            if parsed.get("compra_bolsa"):
                cb = next((d for d in parsed.get("ingresos_detalle", [])
                           if "compra" in d["concepto"].lower() and "bolsa" in d["concepto"].lower()), {})
                lineas.append({"grupo": "ingresos", "concepto": "Compra en bolsa", "valor": -abs(parsed["compra_bolsa"]), **_orig(cb)})

    # COMERCIALIZACIÓN XM (desglosada)
    for c in parsed.get("comercializacion", []):
        lineas.append({"grupo": "comercializacion", "concepto": c["concepto"], "valor": c["valor"], **_orig(c)})

    # COSTOS OPERATIVOS (IVA 19% como línea aparte sobre mantenimiento e internet)
    for c in parsed.get("costos", []):
        lineas.append({"grupo": "costos", "concepto": c["concepto"], "valor": c["valor"], **_orig(c)})
        if c.get("iva"):
            lineas.append({
                "grupo": "costos",
                "concepto": f"IVA {c['concepto']}",
                "valor": round(c["valor"] * IVA, 2),
                "hoja": None, "celda": None,  # el IVA es derivado, no es una celda del ER
            })

    # FACTURAS DE SERVICIO
    for f in parsed.get("facturas", []):
        lineas.append({"grupo": "facturas", "concepto": f["concepto"], "valor": f["valor"], **_orig(f)})

    return lineas


def _rango_periodo(periodo: str) -> tuple[date, date]:
    """Devuelve (primer_dia, ultimo_dia) del mes 'YYYY-MM'."""
    y, m = (int(x) for x in periodo.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _inversionistas_de(db: Session, proyecto_id: int, periodo: str | None = None) -> list[dict]:
    rows = (
        db.query(
            ProyectoInversionista.id,
            ProyectoInversionista.porcentaje_participacion,
            ProyectoInversionista.fecha_inicio,
            ProyectoInversionista.fecha_fin,
            Cliente.razon_social_nombre,
        )
        .outerjoin(Cliente, ProyectoInversionista.cliente_id == Cliente.id)
        .filter(ProyectoInversionista.proyecto_id == proyecto_id)
        .all()
    )

    # Filtrar por período: solo inversionistas activos durante el mes. Un
    # inversionista está activo si empezó antes del fin de mes y no terminó antes
    # de que empiece (misma lógica que match_inversionista de liquidaciones).
    if periodo:
        ini, fin = _rango_periodo(periodo)
        activos = [
            r for r in rows
            if (r.fecha_inicio is None or r.fecha_inicio <= fin)
            and (r.fecha_fin is None or r.fecha_fin >= ini)
        ]
        # Si el filtro deja a todos fuera (datos sin fechas o inconsistentes),
        # caer al conjunto completo para no perder la división.
        if activos:
            rows = activos

    # porcentaje_participacion puede venir en 0-1 (0.5 = 50%) o en 0-100 (50 = 50%)
    # según cómo se cargó cada proyecto (datos inconsistentes en proyecto_inversionistas).
    # Detección ROBUSTA por la SUMA de los porcentajes activos (no por un umbral por
    # valor, que era frágil): la participación total de un proyecto siempre debe
    # acercarse a "el 100%". Si la suma está más cerca de 1 que de 100, los datos
    # están en fracción (0-1); si está más cerca de 100, están en 0-100.
    #   - normal/NEU/NITRO con datos 0-1 (ej. Cacica 0.5/0.5 → suma 1.0)  → fracción
    #   - un único inversionista al 100% guardado como 1.0 (suma 1.0)     → fracción → 100%
    #   - datos 0-100 (ej. 60/40 → suma 100)                              → 0-100
    # Esto corrige el bug de que single 1.0 mostraba "1%" y El Son 0.21 mostraba "0.21%".
    pcts = [float(r.porcentaje_participacion) for r in rows if r.porcentaje_participacion is not None]
    suma = sum(pcts)
    # Si la suma está más cerca de 1 que de 100 ⇒ escala fracción (0-1); si no ⇒ 0-100.
    # Comparar distancias (no un umbral por valor) tolera sumas parciales cuando no
    # todos los inversionistas están activos el mes completo (ej. El Son en mayo).
    escala_0_1 = bool(pcts) and abs(suma - 1.0) <= abs(suma - 100.0)

    out = []
    for r in rows:
        raw = float(r.porcentaje_participacion) if r.porcentaje_participacion is not None else None
        # pct = porcentaje en forma 0-100 (lo que se muestra y se guarda en la línea);
        # fraccion = factor 0-1 para dividir los valores.
        if raw is None:
            pct = fraccion = None
        elif escala_0_1:
            pct, fraccion = raw * 100.0, raw
        else:
            pct, fraccion = raw, raw / 100.0
        out.append({
            "id": r.id,
            "nombre": r.razon_social_nombre or "—",
            "fraccion": fraccion,
            "pct": pct,
        })
    # Si ningún % está definido, repartir en partes iguales como fallback.
    sin_pct = [o for o in out if o["fraccion"] is None]
    if out and sin_pct:
        falt = 1.0 - sum(o["fraccion"] or 0 for o in out if o["fraccion"] is not None)
        cada = (falt / len(sin_pct)) if falt > 0 else (1.0 / len(out))
        for o in sin_pct:
            o["fraccion"] = cada
            o["pct"] = cada * 100
    return out


# ── Cargar ER ──────────────────────────────────────────────────────────────────

@router.post("/cargar-er")
async def cargar_er(
    files: list[UploadFile] = File(...),
    periodo: str = Form(...),
    tipo: str = Form("preliquidacion"),
    tipo_carga: str = Form("normal"),
    db: Session = Depends(get_db),
    current: Usuario = Depends(_require_write),
):
    """
    Sube uno o varios ER. Por cada archivo: recalcula con LibreOffice, parsea,
    matchea el proyecto, divide por % del backend y guarda el panel + líneas.
    periodo: YYYY-MM. tipo: 'preliquidacion' | 'oficial'.
    tipo_carga: 'normal' | 'neu' | 'nitro' — cómo se lee la sección de ingresos.

    VALIDACIÓN CRUZADA: cada ER debe cargarse en su sección. Si el proyecto está
    clasificado distinto a `tipo_carga` para el período, se rechaza (no se guarda)
    y se reporta aparte, sin romper la carga de los válidos.
    """
    tipo = (tipo or "preliquidacion").strip().lower()
    if tipo not in ("preliquidacion", "oficial"):
        raise HTTPException(422, "tipo debe ser 'preliquidacion' u 'oficial'")
    tipo_carga = (tipo_carga or "normal").strip().lower()
    if tipo_carga not in ("normal", "neu", "nitro"):
        raise HTTPException(422, "tipo_carga debe ser 'normal', 'neu' o 'nitro'")
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    # Solo minigranjas operativas: un ER de otro tipo de proyecto no debe crear panel.
    proyectos_db = [
        {"id": p.id, "nombre_comercial": p.nombre_comercial}
        for p in db.query(Proyecto).filter(_es_minigranja_operativa())
        .order_by(Proyecto.id).all()
    ]

    # Clasificación del período: proyecto_id → tipo (default 'normal').
    clasif_map = {
        c.proyecto_id: c.tipo
        for c in db.query(ClasificacionLiquidacion)
        .filter(ClasificacionLiquidacion.periodo == periodo_norm).all()
    }

    # Mapeos guardados: proyecto_id → {concepto_norm: {hoja, celda}}. Si existe un
    # mapeo confirmado para (proyecto, concepto), el parser lee ESA celda.
    mapeos_por_proyecto: dict[int, dict] = {}
    for m in db.query(MapeoCeldaConcepto).all():
        mapeos_por_proyecto.setdefault(m.proyecto_id, {})[_norm_concepto(m.concepto)] = {
            "hoja": m.hoja, "celda": m.celda,
        }

    # Alias de fuentes de ingreso: proyecto_id → {columna_origen.lower(): {etiqueta, orden}}.
    aliases_por_proyecto: dict[int, dict] = {}
    for a in db.query(AliasFuenteIngreso).all():
        aliases_por_proyecto.setdefault(a.proyecto_id, {})[a.columna_origen.lower()] = {
            "etiqueta": a.etiqueta, "orden": a.orden,
        }

    resultados = {
        "cargados": [], "sin_match": [], "errores": [],
        "warnings": [], "duplicados": [], "rechazados": [],
    }
    proyectos_vistos: set[int] = set()

    for uf in files:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        recalc_path = None
        try:
            tmp.write(await uf.read())
            tmp.flush()
            tmp.close()

            # El proyecto va al final del nombre de archivo; ventanas deslizantes.
            proy = extraer_proyecto_de_archivo(uf.filename or "", proyectos_db)
            if not proy:
                resultados["sin_match"].append(uf.filename)
                continue

            # Multi-ER: cada ER es el 100% del proyecto. Si ya cargamos uno de
            # este proyecto en esta llamada, ignoramos los demás (El Son, Baraya…).
            if proy["id"] in proyectos_vistos:
                resultados["duplicados"].append({
                    "archivo": uf.filename, "proyecto": proy["nombre_comercial"],
                })
                continue

            # Validación cruzada: la clasificación del período debe coincidir con
            # el tipo de carga elegido.
            clasif = clasif_map.get(proy["id"], "normal")
            if clasif != tipo_carga:
                resultados["rechazados"].append({
                    "archivo": uf.filename,
                    "proyecto": proy["nombre_comercial"],
                    "clasificacion": clasif,
                    "tipo_carga": tipo_carga,
                    "mensaje": (
                        f"{proy['nombre_comercial']} está clasificado como "
                        f"{clasif.upper()} para {periodo_norm}, debe cargarse en "
                        f"su sección correspondiente"
                    ),
                })
                continue

            proyectos_vistos.add(proy["id"])

            recalc_path = recalcular_er(tmp.name)
            parsed = parsear_er(
                recalc_path, tipo=tipo_carga,
                mapeos=mapeos_por_proyecto.get(proy["id"]),
                aliases=aliases_por_proyecto.get(proy["id"]),
                proyecto_nombre=proy["nombre_comercial"],
            )

            panel = _guardar_panel(
                db, proy["id"], periodo_norm, tipo, parsed,
                er_filename=uf.filename, usuario_id=current.id,
            )
            resultados["cargados"].append({
                "panel_id": panel.id,
                "proyecto_id": proy["id"],
                "proyecto": proy["nombre_comercial"],
                "archivo": uf.filename,
                "ingreso_bruto": float(panel.ingreso_bruto_cop or 0),
            })
            if parsed.get("warnings"):
                resultados["warnings"].append({"archivo": uf.filename, "detalle": parsed["warnings"]})
        except Exception as e:
            logger.exception("Error procesando ER %s", uf.filename)
            resultados["errores"].append({"archivo": uf.filename, "error": str(e)})
            db.rollback()
        finally:
            for p in (tmp.name, recalc_path):
                if p and os.path.exists(p) and p != tmp.name + "__keep":
                    try:
                        os.unlink(p)
                    except Exception:
                        pass

    return {"ok": True, "periodo": periodo_norm, "tipo": tipo, "tipo_carga": tipo_carga, **resultados}


def _guardar_panel(
    db: Session, proyecto_id: int, periodo: str, tipo: str,
    parsed: dict, er_filename: str | None, usuario_id: int,
) -> PanelContable:
    panel = (
        db.query(PanelContable)
        .filter(
            PanelContable.proyecto_id == proyecto_id,
            PanelContable.periodo == periodo,
            PanelContable.tipo == tipo,
        )
        .first()
    )
    if panel is None:
        panel = PanelContable(proyecto_id=proyecto_id, periodo=periodo, tipo=tipo)
        db.add(panel)
        db.flush()  # asignar panel.id antes de insertar líneas
    else:
        # Recarga (reemplazo): borrar líneas previas con un único DELETE en vez de
        # eliminar fila por fila vía ORM, que con decenas de paneles se vuelve tan
        # lento que el proxy corta la petición (504 → "Fallo al procesar ER").
        # Se preservan los flags/consecutivos del panel.
        db.query(PanelContableLinea).filter(
            PanelContableLinea.panel_id == panel.id
        ).delete(synchronize_session=False)
        db.expire(panel, ["lineas"])

    base = _construir_lineas_base(parsed)
    tiene_costos = any(l["grupo"] == "costos" for l in base)

    panel.ingreso_bruto_cop = parsed["ingreso_bruto"]
    panel.comercializador = parsed.get("comercializador")
    panel.tiene_bolsa = bool(parsed.get("tiene_bolsa"))
    panel.tiene_costos = tiene_costos
    # Sin costos → no se puede liquidar costos (checkbox deshabilitado en la vista).
    if not tiene_costos:
        panel.liquidar_costos = False
    panel.er_filename = er_filename
    # Snapshot del ER recalculado: permite releer una celda al cambiar el mapeo
    # sin re-subir el archivo. Se guarda como JSON {hoja: {coord: valor}}.
    snap = parsed.get("snapshot") or {}
    panel.er_snapshot = json.dumps(snap) if snap else None
    panel.generado_por_id = usuario_id
    db.flush()

    invs = _inversionistas_de(db, proyecto_id, periodo)
    if not invs:
        invs = [{"id": None, "nombre": "Sin inversionistas", "fraccion": 1.0, "pct": 100.0}]

    orden = 0
    for inv in invs:
        frac = inv["fraccion"] if inv["fraccion"] is not None else 0.0
        for l in base:
            db.add(PanelContableLinea(
                panel_id=panel.id,
                proyecto_inversionista_id=inv["id"],
                inversionista_nombre=inv["nombre"],
                porcentaje=inv["pct"],
                grupo=l["grupo"],
                concepto=l["concepto"],
                valor_cop=round(l["valor"] * frac, 2),
                hoja=l.get("hoja"),
                celda=l.get("celda"),
                orden=orden,
            ))
            orden += 1

    db.commit()
    db.refresh(panel)
    return panel


# ── Clasificación de liquidación por período ────────────────────────────────────

@router.get("/clasificacion")
def listar_clasificacion(
    periodo: str = Query(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Todos los proyectos con su tipo de liquidación asignado para el período
    ('normal' por defecto si no tiene registro). La clasificación es POR PERÍODO.
    """
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    asignados = {
        c.proyecto_id: c.tipo
        for c in db.query(ClasificacionLiquidacion)
        .filter(ClasificacionLiquidacion.periodo == periodo_norm).all()
    }
    # El Panel Contable es SOLO de minigranjas operativas: filtrar para no listar
    # AMC, Acanto, los COLxxx, etc. (mismo filtro que en cargar-er).
    proyectos = (
        db.query(Proyecto)
        .filter(_es_minigranja_operativa())
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    return {
        "periodo": periodo_norm,
        "proyectos": [
            {
                "proyecto_id": p.id,
                "proyecto": p.nombre_comercial,
                "tipo": asignados.get(p.id, "normal"),
            }
            for p in proyectos
        ],
    }


@router.post("/clasificacion")
def guardar_clasificacion(
    body: ClasificacionBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Upsert de la clasificación del período. Solo persiste las que difieren de
    'normal' (default); reasignar a 'normal' elimina el registro previo.
    """
    try:
        y, m = body.periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    existentes = {
        c.proyecto_id: c
        for c in db.query(ClasificacionLiquidacion)
        .filter(ClasificacionLiquidacion.periodo == periodo_norm).all()
    }
    guardados = 0
    for a in body.asignaciones:
        tipo = (a.tipo or "normal").strip().lower()
        if tipo not in ("normal", "neu", "nitro"):
            raise HTTPException(422, f"tipo inválido para proyecto {a.proyecto_id}: {a.tipo}")
        actual = existentes.get(a.proyecto_id)
        if tipo == "normal":
            # 'normal' es el default → no se almacena; eliminar registro previo.
            if actual is not None:
                db.delete(actual)
                guardados += 1
            continue
        if actual is None:
            db.add(ClasificacionLiquidacion(
                proyecto_id=a.proyecto_id, periodo=periodo_norm, tipo=tipo,
            ))
        else:
            actual.tipo = tipo
        guardados += 1

    db.commit()
    return {"ok": True, "periodo": periodo_norm, "guardados": guardados}


# ── Listar ─────────────────────────────────────────────────────────────────────

@router.get("")
def listar(
    periodo: str = Query(...),
    tipo: str = Query("preliquidacion"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    paneles = (
        db.query(PanelContable)
        .options(selectinload(PanelContable.lineas))
        .filter(PanelContable.periodo == periodo_norm, PanelContable.tipo == tipo)
        .order_by(PanelContable.id)
        .all()
    )

    nombres = {
        p.id: p.nombre_comercial
        for p in db.query(Proyecto.id, Proyecto.nombre_comercial).all()
    }

    return {
        "periodo": periodo_norm,
        "tipo": tipo,
        "paneles": [_serializar_panel(p, nombres) for p in paneles],
    }


def _serializar_panel(p: PanelContable, nombres: dict) -> dict:
    # Agrupar líneas por inversionista.
    inv_map: dict = {}
    for ln in sorted(p.lineas, key=lambda x: x.orden):
        key = ln.proyecto_inversionista_id or f"_{ln.inversionista_nombre}"
        if key not in inv_map:
            inv_map[key] = {
                "proyecto_inversionista_id": ln.proyecto_inversionista_id,
                "nombre": ln.inversionista_nombre,
                "porcentaje": float(ln.porcentaje) if ln.porcentaje is not None else None,
                "lineas": [],
            }
        inv_map[key]["lineas"].append({
            "id": ln.id,
            "grupo": ln.grupo,
            "concepto": ln.concepto,
            "valor_cop": float(ln.valor_cop) if ln.valor_cop is not None else 0.0,
            "comprobante_contable": ln.comprobante_contable,
            "hoja": ln.hoja,
            "celda": ln.celda,
            # "hoja!celda" listo para mostrar/editar en el frontend (None si es derivado).
            "origen": f"{ln.hoja}!{ln.celda}" if (ln.hoja and ln.celda) else None,
            "orden": ln.orden,
        })

    # Vista 100%: el valor TOTAL del proyecto por concepto (suma de todos los
    # inversionistas, = antes de dividir). Preserva el orden de aparición.
    total_100: list[dict] = []
    idx_100: dict = {}
    for ln in sorted(p.lineas, key=lambda x: x.orden):
        k = (ln.grupo, ln.concepto)
        v = float(ln.valor_cop) if ln.valor_cop is not None else 0.0
        if k not in idx_100:
            idx_100[k] = len(total_100)
            total_100.append({
                "grupo": ln.grupo, "concepto": ln.concepto, "valor_cop": v,
                "hoja": ln.hoja, "celda": ln.celda,
                "origen": f"{ln.hoja}!{ln.celda}" if (ln.hoja and ln.celda) else None,
                "comprobante_contable": ln.comprobante_contable, "orden": ln.orden,
            })
        else:
            total_100[idx_100[k]]["valor_cop"] += v

    return {
        "id": p.id,
        "proyecto_id": p.proyecto_id,
        "proyecto": nombres.get(p.proyecto_id, f"Proyecto {p.proyecto_id}"),
        "periodo": p.periodo,
        "tipo": p.tipo,
        "liquidar": p.liquidar,
        "liquidar_ingresos": p.liquidar_ingresos,
        "liquidar_costos": p.liquidar_costos,
        "generar_mandatos": p.generar_mandatos,
        "tiene_bolsa": p.tiene_bolsa,
        "tiene_costos": p.tiene_costos,
        "comercializador": p.comercializador,
        "ingreso_bruto_cop": float(p.ingreso_bruto_cop) if p.ingreso_bruto_cop is not None else 0.0,
        "fecha_firma": p.fecha_firma.isoformat() if p.fecha_firma else None,
        "consecutivo_ingresos": p.consecutivo_ingresos,
        "consecutivo_costos": p.consecutivo_costos,
        "er_filename": p.er_filename,
        "inversionistas": list(inv_map.values()),
        # Vista 100% (total proyecto sin dividir).
        "total_100": total_100,
    }


# ── Re-división: refrescar el reparto por inversionista sin re-subir el ER ──────
#
# Las líneas de un panel son un SNAPSHOT dividido al momento de cargar el ER. Si el
# panel se generó con un % mal escalado (ej. una versión vieja que trataba la
# fracción 1.0 como "1%" → valores 100× menores), `listar` sigue sirviendo ese
# snapshot: recargar el ER es el único refresco y depende de LibreOffice en Railway.
# Estas funciones puras reconstruyen la base al 100% desde las propias líneas y
# vuelven a repartir con los % actuales, sin archivo ni recálculo.

def _linea_dict(ln) -> dict:
    return {
        "proyecto_inversionista_id": ln.proyecto_inversionista_id,
        "porcentaje": float(ln.porcentaje) if ln.porcentaje is not None else None,
        "valor_cop": float(ln.valor_cop) if ln.valor_cop is not None else 0.0,
        "grupo": ln.grupo, "concepto": ln.concepto,
        "hoja": ln.hoja, "celda": ln.celda,
        "comprobante_contable": ln.comprobante_contable, "orden": ln.orden,
    }


def _reconstruir_base(lineas: list[dict]) -> list[dict]:
    """
    Renglones al 100% (sin dividir) a partir de las líneas YA divididas, usando el
    invariante de generación: valor_cop = base · (porcentaje / 100). Por tanto
    base = Σ valor_cop / Σ (porcentaje / 100) por (grupo, concepto). El invariante
    se cumple en ambas ramas de _inversionistas_de (fracción y 0-100), así que la
    reconstrucción es correcta sin importar con qué escala se generó el snapshot.
    Conserva orden de aparición, celda de origen y comprobante.
    """
    bases: list[dict] = []
    idx: dict = {}
    for ln in sorted(lineas, key=lambda x: x["orden"]):
        k = (ln["grupo"], ln["concepto"])
        if k not in idx:
            idx[k] = len(bases)
            bases.append({
                "grupo": ln["grupo"], "concepto": ln["concepto"],
                "hoja": ln.get("hoja"), "celda": ln.get("celda"),
                "comprobante_contable": ln.get("comprobante_contable"),
                "_sum_val": 0.0, "_sum_frac": 0.0,
            })
        b = bases[idx[k]]
        pct = ln.get("porcentaje")
        b["_sum_val"] += ln.get("valor_cop") or 0.0
        b["_sum_frac"] += (pct / 100.0) if pct else 0.0
        if not b.get("comprobante_contable") and ln.get("comprobante_contable"):
            b["comprobante_contable"] = ln["comprobante_contable"]
    for b in bases:
        # Σfrac ≈ 0 (todos los % en 0/None) ⇒ no se puede des-dividir; se deja el
        # valor tal cual para no inventar una base.
        b["valor"] = (b["_sum_val"] / b["_sum_frac"]) if b["_sum_frac"] else b["_sum_val"]
    return bases


def _redividir_lineas(lineas: list[dict], invs: list[dict]) -> list[dict]:
    """
    Reparte de nuevo las líneas por inversionista con los % de `invs` (mismo formato
    que _inversionistas_de). Replica el orden de _guardar_panel (inversionista
    externo, concepto interno). Idempotente si los % no cambian.
    """
    bases = _reconstruir_base(lineas)
    out: list[dict] = []
    orden = 0
    for inv in invs:
        frac = inv["fraccion"] if inv["fraccion"] is not None else 0.0
        for b in bases:
            out.append({
                "proyecto_inversionista_id": inv["id"],
                "inversionista_nombre": inv["nombre"],
                "porcentaje": inv["pct"],
                "grupo": b["grupo"], "concepto": b["concepto"],
                "valor_cop": round(b["valor"] * frac, 2),
                "hoja": b["hoja"], "celda": b["celda"],
                "comprobante_contable": b["comprobante_contable"],
                "orden": orden,
            })
            orden += 1
    return out


def _division_desactualizada(lineas: list[dict], invs: list[dict], tol: float = 0.01) -> bool:
    """
    True si el % por inversionista guardado en las líneas NO coincide con el correcto
    (invs). Evita repisar paneles sanos o con ediciones manuales: solo se re-divide
    cuando el reparto está realmente mal escalado o cambió la composición.
    """
    correcto = {i["id"]: i["pct"] for i in invs if i["id"] is not None and i["pct"] is not None}
    if not correcto:
        return False
    guardado: dict = {}
    for ln in lineas:
        pid = ln.get("proyecto_inversionista_id")
        if pid is not None and ln.get("porcentaje") is not None:
            guardado[pid] = float(ln["porcentaje"])
    if set(guardado) != set(correcto):
        return True
    return any(abs(guardado[k] - correcto[k]) > tol for k in correcto)


@router.post("/redividir")
def redividir(
    body: RedividirBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Refresca el reparto por inversionista de los paneles de un período usando los %
    actuales de proyecto_inversionistas, SIN re-subir el ER. Repara paneles cuyas
    líneas quedaron mal escaladas por una generación previa (ej. % en fracción →
    valores 100× menores). Reconstruye la base al 100% desde las propias líneas, así
    no depende de LibreOffice ni del archivo. Seguro e idempotente: salta los paneles
    cuyo % ya coincide (preserva ediciones), salvo forzar=True.
    """
    try:
        y, m = body.periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    q = (
        db.query(PanelContable)
        .options(selectinload(PanelContable.lineas))
        .filter(PanelContable.periodo == periodo_norm, PanelContable.tipo == body.tipo)
    )
    if body.proyecto_id is not None:
        q = q.filter(PanelContable.proyecto_id == body.proyecto_id)
    paneles = q.order_by(PanelContable.id).all()

    redivididos, saltados = [], []
    for panel in paneles:
        lineas = [_linea_dict(ln) for ln in panel.lineas]
        if not lineas:
            saltados.append({"panel_id": panel.id, "proyecto_id": panel.proyecto_id, "motivo": "sin_lineas"})
            continue
        invs = _inversionistas_de(db, panel.proyecto_id, periodo_norm)
        if not invs:
            invs = [{"id": None, "nombre": "Sin inversionistas", "fraccion": 1.0, "pct": 100.0}]
        if not body.forzar and not _division_desactualizada(lineas, invs):
            saltados.append({"panel_id": panel.id, "proyecto_id": panel.proyecto_id, "motivo": "ya_correcto"})
            continue
        nuevas = _redividir_lineas(lineas, invs)
        db.query(PanelContableLinea).filter(
            PanelContableLinea.panel_id == panel.id
        ).delete(synchronize_session=False)
        for nl in nuevas:
            db.add(PanelContableLinea(panel_id=panel.id, **nl))
        redivididos.append({
            "panel_id": panel.id, "proyecto_id": panel.proyecto_id,
            "lineas": len(nuevas),
            "porcentajes": sorted({round(i["pct"], 4) for i in invs if i["pct"] is not None}),
        })
    db.commit()
    return {
        "ok": True, "periodo": periodo_norm, "tipo": body.tipo,
        "n_redivididos": len(redivididos), "n_saltados": len(saltados),
        "redivididos": redivididos, "saltados": saltados,
    }


# ── Editar panel / líneas ────────────────────────────────────────────────────────

@router.patch("/{panel_id}")
def actualizar(
    panel_id: int,
    body: PanelPatch,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    panel = db.query(PanelContable).filter(PanelContable.id == panel_id).first()
    if not panel:
        raise HTTPException(404, "Panel no encontrado")

    for campo in ("liquidar", "liquidar_ingresos", "liquidar_costos",
                  "generar_mandatos", "fecha_firma",
                  "consecutivo_ingresos", "consecutivo_costos"):
        val = getattr(body, campo)
        if val is not None:
            setattr(panel, campo, val)

    if body.lineas:
        ids = {l.id: l for l in body.lineas}
        lineas = (
            db.query(PanelContableLinea)
            .filter(PanelContableLinea.id.in_(list(ids.keys())),
                    PanelContableLinea.panel_id == panel_id)
            .all()
        )
        for ln in lineas:
            patch = ids[ln.id]
            if patch.valor_cop is not None:
                ln.valor_cop = patch.valor_cop
            if patch.comprobante_contable is not None:
                ln.comprobante_contable = patch.comprobante_contable
            if patch.concepto is not None:
                ln.concepto = patch.concepto

    db.commit()
    db.refresh(panel)
    nombres = {panel.proyecto_id: None}
    p = db.query(Proyecto.nombre_comercial).filter(Proyecto.id == panel.proyecto_id).first()
    nombres[panel.proyecto_id] = p.nombre_comercial if p else None
    return _serializar_panel(panel, nombres)


# ── Mapeo de celda por concepto (PROPONER → CORREGIR → RECORDAR) ──────────────────

@router.post("/mapeo-celda")
def guardar_mapeo_celda(
    body: MapeoCeldaBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    La usuaria corrige la celda de origen de un concepto ("hoja!celda"). El backend:
      1. relee esa celda del snapshot del ER del panel,
      2. guarda el mapeo por (proyecto, concepto) para los próximos meses (RECORDAR),
      3. actualiza el valor de las líneas de ese concepto (re-dividido por inversionista).
    Devuelve el panel actualizado.
    """
    try:
        y, m = body.periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    hoja = (body.hoja or "").strip()
    celda = (body.celda or "").strip().upper().replace("$", "")
    if not hoja or not celda:
        raise HTTPException(422, "Debe indicar hoja y celda (ej. Sheet1 / H35)")

    panel = (
        db.query(PanelContable)
        .filter(
            PanelContable.proyecto_id == body.proyecto_id,
            PanelContable.periodo == periodo_norm,
            PanelContable.tipo == body.tipo,
        )
        .first()
    )
    if not panel:
        raise HTTPException(404, "No hay panel para ese proyecto/período/tipo")
    if not panel.er_snapshot:
        raise HTTPException(
            409, "El panel no tiene snapshot del ER (vuelve a cargar el ER para poder remapear celdas)"
        )

    snapshot = json.loads(panel.er_snapshot)
    val = leer_celda(snapshot, hoja, celda)
    if val is None:
        raise HTTPException(422, f"{hoja}!{celda} no tiene un valor numérico en el ER")

    # Upsert del mapeo persistente (RECORDAR).
    mapeo = (
        db.query(MapeoCeldaConcepto)
        .filter(
            MapeoCeldaConcepto.proyecto_id == body.proyecto_id,
            MapeoCeldaConcepto.concepto == body.concepto,
        )
        .first()
    )
    if mapeo is None:
        mapeo = MapeoCeldaConcepto(
            proyecto_id=body.proyecto_id, concepto=body.concepto, hoja=hoja, celda=celda,
        )
        db.add(mapeo)
    else:
        mapeo.hoja = hoja
        mapeo.celda = celda

    # Actualizar las líneas de ese concepto (re-divididas por % del inversionista).
    lineas = (
        db.query(PanelContableLinea)
        .filter(PanelContableLinea.panel_id == panel.id,
                PanelContableLinea.concepto == body.concepto)
        .all()
    )
    if not lineas:
        raise HTTPException(404, f"El panel no tiene el concepto '{body.concepto}'")
    for ln in lineas:
        base = _aplicar_signo(ln.grupo, ln.concepto, val)
        frac = (float(ln.porcentaje) / 100.0) if ln.porcentaje is not None else 1.0
        ln.valor_cop = round(base * frac, 2)
        ln.hoja = hoja
        ln.celda = celda

    db.commit()
    db.refresh(panel)
    nombres = {}
    p = db.query(Proyecto.nombre_comercial).filter(Proyecto.id == panel.proyecto_id).first()
    nombres[panel.proyecto_id] = p.nombre_comercial if p else None
    return _serializar_panel(panel, nombres)


# ── Fuentes de ingreso: alias persistente + agregar/quitar (Fase 2) ───────────────

def _split_columna_origen(s: str) -> tuple[str, str]:
    """'Sheet1!G35' → ('Sheet1', 'G35'). 422 si el formato es inválido."""
    if not s or "!" not in s:
        raise HTTPException(422, "columna_origen debe ser 'hoja!celda' (ej. Sheet1!G35)")
    hoja, celda = s.split("!", 1)
    hoja = hoja.strip()
    celda = celda.strip().upper().replace("$", "")
    if not hoja or not celda:
        raise HTTPException(422, "columna_origen debe ser 'hoja!celda' (ej. Sheet1!G35)")
    return hoja, celda


def _panel_para(db: Session, proyecto_id: int, periodo: str, tipo: str) -> PanelContable:
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")
    panel = (
        db.query(PanelContable)
        .filter(PanelContable.proyecto_id == proyecto_id,
                PanelContable.periodo == periodo_norm,
                PanelContable.tipo == tipo)
        .first()
    )
    if not panel:
        raise HTTPException(404, "No hay panel para ese proyecto/período/tipo")
    return panel


def _panel_serializado(db: Session, panel: PanelContable) -> dict:
    db.refresh(panel)
    p = db.query(Proyecto.nombre_comercial).filter(Proyecto.id == panel.proyecto_id).first()
    return _serializar_panel(panel, {panel.proyecto_id: p.nombre_comercial if p else None})


@router.post("/alias-fuente")
def guardar_alias_fuente(
    body: AliasFuenteBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    La usuaria renombra una fuente de ingreso (etiqueta) anclada a su celda de
    origen. Guarda el alias (RECORDAR, para el próximo mes), relee el valor de esa
    celda del snapshot y renombra/actualiza las líneas de ingreso de esa fuente.
    """
    hoja, celda = _split_columna_origen(body.columna_origen)
    col = f"{hoja}!{celda}"
    panel = _panel_para(db, body.proyecto_id, body.periodo, body.tipo)

    # Upsert del alias (RECORDAR).
    alias = (
        db.query(AliasFuenteIngreso)
        .filter(AliasFuenteIngreso.proyecto_id == body.proyecto_id,
                AliasFuenteIngreso.columna_origen == col)
        .first()
    )
    if alias is None:
        alias = AliasFuenteIngreso(
            proyecto_id=body.proyecto_id, columna_origen=col,
            etiqueta=body.etiqueta, orden=body.orden or 0,
        )
        db.add(alias)
    else:
        alias.etiqueta = body.etiqueta
        if body.orden is not None:
            alias.orden = body.orden

    # Relabelar (y revalorar) las líneas de ingreso de esa celda.
    val = leer_celda(json.loads(panel.er_snapshot), hoja, celda) if panel.er_snapshot else None
    lineas = (
        db.query(PanelContableLinea)
        .filter(PanelContableLinea.panel_id == panel.id,
                PanelContableLinea.grupo == "ingresos",
                PanelContableLinea.celda == celda)
        .all()
    )
    for ln in lineas:
        if (ln.hoja or "").lower() != hoja.lower():
            continue
        ln.concepto = body.etiqueta
        if val is not None:
            base = _aplicar_signo("ingresos", body.etiqueta, val)
            frac = (float(ln.porcentaje) / 100.0) if ln.porcentaje is not None else 1.0
            ln.valor_cop = round(base * frac, 2)

    db.commit()
    return _panel_serializado(db, panel)


@router.post("/fuente-ingreso")
def agregar_fuente_ingreso(
    body: FuenteIngresoBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Agrega a mano una fuente de ingreso que el parser no detectó (ej. una celda de
    PPA). Lee el valor de la celda del snapshot, crea una línea por inversionista y
    guarda el alias para que reaparezca el próximo mes.
    """
    hoja = (body.hoja or "").strip()
    celda = (body.celda or "").strip().upper().replace("$", "")
    if not hoja or not celda:
        raise HTTPException(422, "Debe indicar hoja y celda (ej. Sheet1 / G35)")
    panel = _panel_para(db, body.proyecto_id, body.periodo, body.tipo)
    if not panel.er_snapshot:
        raise HTTPException(409, "El panel no tiene snapshot del ER (recarga el ER)")
    val = leer_celda(json.loads(panel.er_snapshot), hoja, celda)
    if val is None:
        raise HTTPException(422, f"{hoja}!{celda} no tiene un valor numérico en el ER")

    col = f"{hoja}!{celda}"
    alias = (
        db.query(AliasFuenteIngreso)
        .filter(AliasFuenteIngreso.proyecto_id == body.proyecto_id,
                AliasFuenteIngreso.columna_origen == col)
        .first()
    )
    orden = body.orden if body.orden is not None else 0
    if alias is None:
        db.add(AliasFuenteIngreso(proyecto_id=body.proyecto_id, columna_origen=col,
                                  etiqueta=body.etiqueta, orden=orden))
    else:
        alias.etiqueta = body.etiqueta
        alias.orden = orden

    # Una línea por inversionista, re-dividida por %.
    base = _aplicar_signo("ingresos", body.etiqueta, val)
    invs = _inversionistas_de(db, body.proyecto_id, panel.periodo)
    if not invs:
        invs = [{"id": None, "nombre": "Sin inversionistas", "fraccion": 1.0, "pct": 100.0}]
    orden_max = db.query(func.coalesce(func.max(PanelContableLinea.orden), 0)).filter(
        PanelContableLinea.panel_id == panel.id).scalar() or 0
    for inv in invs:
        frac = inv["fraccion"] if inv["fraccion"] is not None else 0.0
        orden_max += 1
        db.add(PanelContableLinea(
            panel_id=panel.id, proyecto_inversionista_id=inv["id"],
            inversionista_nombre=inv["nombre"], porcentaje=inv["pct"],
            grupo="ingresos", concepto=body.etiqueta,
            valor_cop=round(base * frac, 2), hoja=hoja, celda=celda, orden=orden_max,
        ))
    db.commit()
    return _panel_serializado(db, panel)


@router.delete("/fuente-ingreso")
def quitar_fuente_ingreso(
    body: FuenteIngresoDeleteBody,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Quita una fuente de ingreso (todas sus líneas por inversionista) y borra su
    alias para que no reaparezca el próximo mes.
    """
    hoja, celda = _split_columna_origen(body.columna_origen)
    panel = _panel_para(db, body.proyecto_id, body.periodo, body.tipo)

    borradas = (
        db.query(PanelContableLinea)
        .filter(PanelContableLinea.panel_id == panel.id,
                PanelContableLinea.grupo == "ingresos",
                PanelContableLinea.celda == celda)
        .delete(synchronize_session=False)
    )
    db.query(AliasFuenteIngreso).filter(
        AliasFuenteIngreso.proyecto_id == body.proyecto_id,
        AliasFuenteIngreso.columna_origen == f"{hoja}!{celda}",
    ).delete(synchronize_session=False)
    db.commit()
    panel = _panel_para(db, body.proyecto_id, body.periodo, body.tipo)
    out = _panel_serializado(db, panel)
    out["lineas_borradas"] = borradas
    return out


# ── Reasignar consecutivos en cadena ──────────────────────────────────────────────

@router.post("/reasignar-consecutivos")
def reasignar_consecutivos(
    body: ReasignarConsecutivos,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Asigna consecutivos en dos cadenas independientes:
      - Ingresos: a cada panel con liquidar_ingresos=true.
      - Costos: a cada panel con liquidar_costos=true (decisión del usuario; no se
        exige que el ER haya traído líneas de costos).

    Dos modos (body.solo_faltantes):
      - False (renumerar): reasigna TODO desde el valor inicial, en orden de id.
      - True  (rellenar):  preserva los consecutivos ya asignados (incl. ediciones
        manuales) y solo numera los que están en None, tomando el menor número libre
        ≥ inicial. Así todo panel marcado queda numerado sin pisar lo editado.
    """
    try:
        y, m = body.periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    paneles = (
        db.query(PanelContable)
        .filter(PanelContable.periodo == periodo_norm, PanelContable.tipo == body.tipo)
        .order_by(PanelContable.id)
        .all()
    )
    asignados = _asignar_consecutivos(
        paneles,
        body.consecutivo_ingresos_inicial,
        body.consecutivo_costos_inicial,
        solo_faltantes=body.solo_faltantes,
    )
    db.commit()
    return {"ok": True, "solo_faltantes": body.solo_faltantes, "asignados": asignados}


def _asignar_consecutivos(
    paneles: list[PanelContable], ini_ing: int, ini_cos: int, solo_faltantes: bool,
) -> list[dict]:
    """
    Numera (in-place, sin commit) las dos cadenas de consecutivos. Ver
    reasignar_consecutivos para la semántica de `solo_faltantes`.
    """
    def _cadena(activo, attr, inicio):
        # Números ya ocupados (solo en modo rellenar, para no chocar con ediciones).
        ocupados = set()
        if solo_faltantes:
            ocupados = {
                getattr(p, attr) for p in paneles
                if activo(p) and getattr(p, attr) is not None
            }
        siguiente = inicio

        def _libre():
            nonlocal siguiente
            while siguiente in ocupados:
                siguiente += 1
            n = siguiente
            ocupados.add(n)
            siguiente += 1
            return n

        for p in paneles:
            if not activo(p):
                # No liquida esa cadena → siempre se limpia (no debe tener consecutivo).
                setattr(p, attr, None)
                continue
            if solo_faltantes:
                if getattr(p, attr) is None:
                    setattr(p, attr, _libre())
            else:
                setattr(p, attr, _libre())

    _cadena(lambda p: bool(p.liquidar_ingresos), "consecutivo_ingresos", ini_ing)
    # Costos: se respeta la decisión del usuario (liquidar_costos), sin atarla a si
    # el ER trajo líneas de costos: un proyecto puede tener costos que este mes no
    # llegaron en el ER o que vendrán de la vista de costos. El default de paneles
    # sin costos sigue siendo liquidar_costos=False, así que solo se numeran los
    # que el usuario marca explícitamente.
    _cadena(lambda p: bool(p.liquidar_costos), "consecutivo_costos", ini_cos)

    return [
        {
            "panel_id": p.id,
            "consecutivo_ingresos": p.consecutivo_ingresos,
            "consecutivo_costos": p.consecutivo_costos,
        }
        for p in paneles
    ]


# ── Diferencia preliquidación vs oficial ────────────────────────────────────────

@router.get("/diferencia")
def diferencia(
    periodo: str = Query(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    paneles = (
        db.query(PanelContable)
        .options(selectinload(PanelContable.lineas))
        .filter(PanelContable.periodo == periodo_norm)
        .all()
    )
    nombres = {
        p.id: p.nombre_comercial
        for p in db.query(Proyecto.id, Proyecto.nombre_comercial).all()
    }

    # Indexar paneles por proyecto y tipo.
    pre_por_proy: dict[int, PanelContable] = {}
    ofi_por_proy: dict[int, PanelContable] = {}
    for p in paneles:
        if p.tipo == "preliquidacion":
            pre_por_proy[p.proyecto_id] = p
        elif p.tipo == "oficial":
            ofi_por_proy[p.proyecto_id] = p

    tiene_oficial = bool(ofi_por_proy)
    tiene_preliquidacion = bool(pre_por_proy)

    def _inv_key(ln: PanelContableLinea):
        return ln.proyecto_inversionista_id if ln.proyecto_inversionista_id is not None \
            else f"_{ln.inversionista_nombre}"

    def _indexar_inversionistas(panel: PanelContable | None) -> dict:
        """inv_key → {nombre, porcentaje, orden, lineas: {(grupo,concepto): {valor, orden}}}"""
        out: dict = {}
        if panel is None:
            return out
        for ln in sorted(panel.lineas, key=lambda x: x.orden):
            k = _inv_key(ln)
            inv = out.setdefault(k, {
                "nombre": ln.inversionista_nombre,
                "porcentaje": float(ln.porcentaje) if ln.porcentaje is not None else None,
                "orden": len(out),
                "lineas": {},
            })
            inv["lineas"][(ln.grupo, ln.concepto)] = {
                "valor": float(ln.valor_cop) if ln.valor_cop is not None else 0.0,
                "orden": ln.orden,
            }
        return out

    proyectos_out = []
    tot_pre_global = tot_ofi_global = 0.0
    proyecto_ids = sorted(set(pre_por_proy) | set(ofi_por_proy),
                          key=lambda pid: (pre_por_proy.get(pid) or ofi_por_proy.get(pid)).id)

    for pid in proyecto_ids:
        pre_panel = pre_por_proy.get(pid)
        ofi_panel = ofi_por_proy.get(pid)
        hay_ofi = ofi_panel is not None
        hay_pre = pre_panel is not None

        pre_invs = _indexar_inversionistas(pre_panel)
        ofi_invs = _indexar_inversionistas(ofi_panel)

        # Unión de inversionistas, ordenada por aparición en pre y luego oficial.
        inv_keys = list(pre_invs.keys())
        for k in ofi_invs:
            if k not in inv_keys:
                inv_keys.append(k)

        inversionistas_out = []
        u_pre_proy = u_ofi_proy = 0.0
        for k in inv_keys:
            pi = pre_invs.get(k)
            oi = ofi_invs.get(k)
            nombre = (pi or oi)["nombre"]
            porcentaje = (pi or oi)["porcentaje"]

            # Unión de líneas (grupo, concepto), preservando el orden de pre y
            # añadiendo las que solo existan en oficial.
            claves = []
            vistos = set()
            for src in ((pi["lineas"] if pi else {}), (oi["lineas"] if oi else {})):
                for clave, meta in sorted(src.items(), key=lambda kv: kv[1]["orden"]):
                    if clave not in vistos:
                        vistos.add(clave)
                        claves.append(clave)

            lineas_out = []
            u_pre = u_ofi = 0.0
            for (grupo, concepto) in claves:
                # Si falta uno de los dos paneles, esa columna va en null (no 0).
                if hay_pre:
                    pre_v = pi["lineas"][(grupo, concepto)]["valor"] if (pi and (grupo, concepto) in pi["lineas"]) else 0.0
                else:
                    pre_v = None
                if hay_ofi:
                    ofi_v = oi["lineas"][(grupo, concepto)]["valor"] if (oi and (grupo, concepto) in oi["lineas"]) else 0.0
                else:
                    ofi_v = None
                dif = (ofi_v - pre_v) if (pre_v is not None and ofi_v is not None) else None
                pct = (dif / abs(pre_v) * 100) if (dif is not None and pre_v) else None
                if pre_v is not None:
                    u_pre += pre_v
                if ofi_v is not None:
                    u_ofi += ofi_v
                lineas_out.append({
                    "grupo": grupo,
                    "concepto": concepto,
                    "preliquidacion": round(pre_v, 2) if pre_v is not None else None,
                    "oficial": round(ofi_v, 2) if ofi_v is not None else None,
                    "diferencia": round(dif, 2) if dif is not None else None,
                    "pct_variacion": round(pct, 2) if pct is not None else None,
                })

            u_dif = (u_ofi - u_pre) if (hay_pre and hay_ofi) else None
            inversionistas_out.append({
                "proyecto_inversionista_id": None if isinstance(k, str) else k,
                "nombre": nombre,
                "porcentaje": porcentaje,
                "lineas": lineas_out,
                "utilidad_pre": round(u_pre, 2) if hay_pre else None,
                "utilidad_oficial": round(u_ofi, 2) if hay_ofi else None,
                "utilidad_dif": round(u_dif, 2) if u_dif is not None else None,
            })
            if hay_pre:
                u_pre_proy += u_pre
            if hay_ofi:
                u_ofi_proy += u_ofi

        if hay_pre:
            tot_pre_global += u_pre_proy
        if hay_ofi:
            tot_ofi_global += u_ofi_proy

        proyectos_out.append({
            "proyecto_id": pid,
            "proyecto_nombre": nombres.get(pid, f"Proyecto {pid}"),
            "tiene_preliquidacion": hay_pre,
            "tiene_oficial": hay_ofi,
            "utilidad_pre": round(u_pre_proy, 2) if hay_pre else None,
            "utilidad_oficial": round(u_ofi_proy, 2) if hay_ofi else None,
            "utilidad_dif": round(u_ofi_proy - u_pre_proy, 2) if (hay_pre and hay_ofi) else None,
            "inversionistas": inversionistas_out,
        })

    return {
        "periodo": periodo_norm,
        "tiene_preliquidacion": tiene_preliquidacion,
        "tiene_oficial": tiene_oficial,
        "proyectos": proyectos_out,
        "resumen": {
            "utilidad_estimada": round(tot_pre_global, 2) if tiene_preliquidacion else None,
            "utilidad_real": round(tot_ofi_global, 2) if tiene_oficial else None,
            "diferencia": round(tot_ofi_global - tot_pre_global, 2) if (tiene_preliquidacion and tiene_oficial) else None,
        },
    }
