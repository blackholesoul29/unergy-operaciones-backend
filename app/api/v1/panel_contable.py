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
import logging
import os
import tempfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Usuario
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.clientes import Cliente
from app.models.panel_contable import PanelContable, PanelContableLinea
from app.utils.er_loader import (
    recalcular_er, parsear_er, match_proyecto, normalizar, IVA, FEE_ADMIN,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panel-contable", tags=["Panel Contable"])


def _require_write(current: Usuario = Depends(get_current_user)):
    if current.rol.value not in ("admin", "liquidaciones"):
        raise HTTPException(403, "Se requiere rol admin o liquidaciones")
    return current


# ── Schemas ──────────────────────────────────────────────────────────────────

class LineaPatch(BaseModel):
    id: int
    valor_cop: float | None = None
    comprobante_contable: str | None = None
    concepto: str | None = None


class PanelPatch(BaseModel):
    liquidar: bool | None = None
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


# ── Construcción de líneas a partir del ER parseado ────────────────────────────

def _construir_lineas_base(parsed: dict) -> list[dict]:
    """
    Renglones del ER al 100% (sin dividir). Cada uno: {grupo, concepto, valor}.
    Los totales y la utilidad los calcula el frontend; aquí solo van renglones base.
    """
    lineas: list[dict] = []
    com = parsed.get("comercializador") or ""
    etiqueta_ing = f"Ingreso Bruto{(' ' + com) if com else ''}".strip()

    # INGRESOS
    lineas.append({"grupo": "ingresos", "concepto": etiqueta_ing, "valor": parsed["ingreso_bruto"]})
    if parsed.get("tiene_bolsa"):
        if parsed.get("venta_bolsa"):
            lineas.append({"grupo": "ingresos", "concepto": "Venta en bolsa", "valor": parsed["venta_bolsa"]})
        if parsed.get("compra_bolsa"):
            lineas.append({"grupo": "ingresos", "concepto": "Compra en bolsa", "valor": -abs(parsed["compra_bolsa"])})

    # COMERCIALIZACIÓN XM (desglosada)
    for c in parsed.get("comercializacion", []):
        lineas.append({"grupo": "comercializacion", "concepto": c["concepto"], "valor": c["valor"]})

    # COSTOS OPERATIVOS (IVA 19% como línea aparte sobre mantenimiento e internet)
    for c in parsed.get("costos", []):
        lineas.append({"grupo": "costos", "concepto": c["concepto"], "valor": c["valor"]})
        if c.get("iva"):
            lineas.append({
                "grupo": "costos",
                "concepto": f"IVA {c['concepto']}",
                "valor": round(c["valor"] * IVA, 2),
            })

    # FACTURAS DE SERVICIO
    for f in parsed.get("facturas", []):
        lineas.append({"grupo": "facturas", "concepto": f["concepto"], "valor": f["valor"]})

    return lineas


def _inversionistas_de(db: Session, proyecto_id: int) -> list[dict]:
    rows = (
        db.query(
            ProyectoInversionista.id,
            ProyectoInversionista.porcentaje_participacion,
            Cliente.razon_social_nombre,
        )
        .outerjoin(Cliente, ProyectoInversionista.cliente_id == Cliente.id)
        .filter(ProyectoInversionista.proyecto_id == proyecto_id)
        .all()
    )
    out = []
    for r in rows:
        pct = float(r.porcentaje_participacion) if r.porcentaje_participacion is not None else None
        out.append({
            "id": r.id,
            "nombre": r.razon_social_nombre or "—",
            # porcentaje_participacion se guarda en 0-100; lo normalizamos a fracción.
            "fraccion": (pct / 100.0) if pct is not None else None,
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
    db: Session = Depends(get_db),
    current: Usuario = Depends(_require_write),
):
    """
    Sube uno o varios ER. Por cada archivo: recalcula con LibreOffice, parsea,
    matchea el proyecto, divide por % del backend y guarda el panel + líneas.
    periodo: YYYY-MM. tipo: 'preliquidacion' | 'oficial'.
    """
    tipo = (tipo or "preliquidacion").strip().lower()
    if tipo not in ("preliquidacion", "oficial"):
        raise HTTPException(422, "tipo debe ser 'preliquidacion' u 'oficial'")
    try:
        y, m = periodo.strip().split("-")
        periodo_norm = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    proyectos_db = [
        {"id": p.id, "nombre_comercial": p.nombre_comercial}
        for p in db.query(Proyecto).order_by(Proyecto.id).all()
    ]

    resultados = {"cargados": [], "sin_match": [], "errores": [], "warnings": []}

    for uf in files:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
        recalc_path = None
        try:
            tmp.write(await uf.read())
            tmp.flush()
            tmp.close()

            recalc_path = recalcular_er(tmp.name)
            parsed = parsear_er(recalc_path)

            # Match por nombre de archivo (sin extensión) o por contenido.
            nombre_busqueda = os.path.splitext(uf.filename or "")[0]
            proy = match_proyecto(proyectos_db, nombre_busqueda)
            if not proy:
                resultados["sin_match"].append(uf.filename)
                continue

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

    return {"ok": True, "periodo": periodo_norm, "tipo": tipo, **resultados}


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
    else:
        # Recarga: limpiar líneas previas (preserva flags/consecutivos).
        for ln in list(panel.lineas):
            db.delete(ln)
        db.flush()

    base = _construir_lineas_base(parsed)
    tiene_costos = any(l["grupo"] == "costos" for l in base)

    panel.ingreso_bruto_cop = parsed["ingreso_bruto"]
    panel.comercializador = parsed.get("comercializador")
    panel.tiene_bolsa = bool(parsed.get("tiene_bolsa"))
    panel.tiene_costos = tiene_costos
    panel.er_filename = er_filename
    panel.generado_por_id = usuario_id
    db.flush()

    invs = _inversionistas_de(db, proyecto_id)
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
                orden=orden,
            ))
            orden += 1

    db.commit()
    db.refresh(panel)
    return panel


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
            "orden": ln.orden,
        })

    return {
        "id": p.id,
        "proyecto_id": p.proyecto_id,
        "proyecto": nombres.get(p.proyecto_id, f"Proyecto {p.proyecto_id}"),
        "periodo": p.periodo,
        "tipo": p.tipo,
        "liquidar": p.liquidar,
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

    for campo in ("liquidar", "generar_mandatos", "fecha_firma",
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


# ── Reasignar consecutivos en cadena ──────────────────────────────────────────────

@router.post("/reasignar-consecutivos")
def reasignar_consecutivos(
    body: ReasignarConsecutivos,
    db: Session = Depends(get_db),
    _=Depends(_require_write),
):
    """
    Asigna consecutivos en cadena solo a proyectos con liquidar=true.
    Costos numera únicamente si el panel tiene líneas de costos.
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
    ci = body.consecutivo_ingresos_inicial
    cc = body.consecutivo_costos_inicial
    asignados = []
    for p in paneles:
        if not p.liquidar:
            p.consecutivo_ingresos = None
            p.consecutivo_costos = None
            continue
        p.consecutivo_ingresos = ci
        ci += 1
        if p.tiene_costos:
            p.consecutivo_costos = cc
            cc += 1
        else:
            p.consecutivo_costos = None
        asignados.append({
            "panel_id": p.id,
            "consecutivo_ingresos": p.consecutivo_ingresos,
            "consecutivo_costos": p.consecutivo_costos,
        })
    db.commit()
    return {"ok": True, "asignados": asignados, "siguiente_ingresos": ci, "siguiente_costos": cc}


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

    def _utilidad(panel: PanelContable) -> float:
        return float(sum((ln.valor_cop or 0) for ln in panel.lineas))

    por_proy: dict = {}
    for p in paneles:
        d = por_proy.setdefault(p.proyecto_id, {
            "proyecto_id": p.proyecto_id,
            "proyecto": nombres.get(p.proyecto_id, f"Proyecto {p.proyecto_id}"),
            "preliquidacion": None,
            "oficial": None,
        })
        d[p.tipo] = round(_utilidad(p), 2)

    filas = []
    tot_pre = tot_of = 0.0
    for d in por_proy.values():
        pre = d["preliquidacion"]
        ofi = d["oficial"]
        diff = (ofi - pre) if (pre is not None and ofi is not None) else None
        pct = (diff / abs(pre) * 100) if (diff is not None and pre) else None
        if pre is not None:
            tot_pre += pre
        if ofi is not None:
            tot_of += ofi
        filas.append({
            "proyecto_id": d["proyecto_id"],
            "proyecto": d["proyecto"],
            "preliquidacion": pre,
            "oficial": ofi,
            "diferencia": round(diff, 2) if diff is not None else None,
            "porcentaje": round(pct, 2) if pct is not None else None,
        })

    return {
        "periodo": periodo_norm,
        "filas": filas,
        "resumen": {
            "utilidad_estimada": round(tot_pre, 2),
            "utilidad_real": round(tot_of, 2),
            "diferencia": round(tot_of - tot_pre, 2),
        },
    }
