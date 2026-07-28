"""
Facturación de energía v2 — reproduce el Excel de facturación con datos de la
plataforma:  facturación = kWh(despacho) × tarifa_indexada,  donde
tarifa_indexada = round(tarifa_base_PPA × IPP_mes / IPP_base_PPA, 2)  (redondeo a
2 decimales ANTES de multiplicar, idéntico al Excel de la usuaria).

Fuentes:
  - kWh:  despacho_contrato_mensual (ingerido del archivo XM dspcttos_txf_MM.xlsx)
  - contrato XM → proyecto/PPA:  AsicSolicitud (codigo_sic_contrato, vigente)
  - tarifa base del mes + IPP base:  PPAContrato / PPATarifa
  - IPP del mes:  ipp_mensual
"""
import io
import logging
from calendar import monthrange
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import PPAContrato, PPATarifa, Proyecto, AsicSolicitud
from app.models.contratos import DespachoContratoMensual, IppMensual
from app.models.asic import EstadoSolicitudAsicEnum, TipoSolicitudAsicEnum
from app.utils.gescon_vigencia import resolver_vigencias

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/facturacion", tags=["Facturación"])


def _norm_periodo(periodo: str) -> str:
    try:
        y, m = periodo.strip().split("-")
        return f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")


# ── Ingesta del despacho XM ────────────────────────────────────────────────────
@router.post("/despacho")
async def cargar_despacho(
    periodo: str = Query(..., description="YYYY-MM del despacho"),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Sube el archivo de despachos de XM (xlsx, hoja con CONTRATO + DESP_HORA 01..24)
    y guarda la energía mensual por contrato (suma de las 24 horas de todo el mes).
    Reemplaza el despacho previo del período."""
    import openpyxl
    per = _norm_periodo(periodo)
    contenido = await archivo.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as e:
        raise HTTPException(400, f"No se pudo leer el Excel: {e}")
    ws = wb[wb.sheetnames[0]]

    filas = ws.iter_rows(values_only=True)
    try:
        header = list(next(filas))
    except StopIteration:
        raise HTTPException(400, "El archivo está vacío")
    # Localizar columnas por encabezado.
    def _find(names):
        for i, h in enumerate(header):
            if isinstance(h, str) and h.strip().upper() in names:
                return i
        return None
    i_con = _find({"CONTRATO"})
    i_ven = _find({"VENDEDOR"})
    i_com = _find({"COMPRADOR"})
    i_tipo = _find({"TIPO"})
    if i_con is None:
        raise HTTPException(400, "No encontré la columna CONTRATO en el archivo")
    horas = [i for i, h in enumerate(header)
             if isinstance(h, str) and (h.strip().upper().startswith("DESP_HORA")
                                        or h.strip().upper().replace(" ", "").startswith("H0")
                                        or h.strip().upper().replace(" ", "") in {f"H{n}" for n in range(24)})]
    if not horas:
        raise HTTPException(400, "No encontré columnas de horas (DESP_HORA 01..24)")

    agg: dict = {}
    for r in filas:
        if not r or i_con >= len(r) or r[i_con] is None:
            continue
        con = str(int(r[i_con])) if isinstance(r[i_con], float) else str(r[i_con]).strip()
        kwh = sum(r[i] for i in horas if i < len(r) and isinstance(r[i], (int, float)))
        d = agg.setdefault(con, {"kwh": 0.0, "vendedor": None, "comprador": None, "tipo": None})
        d["kwh"] += kwh
        if i_ven is not None and i_ven < len(r) and r[i_ven]:
            d["vendedor"] = str(r[i_ven]).strip()
        if i_com is not None and i_com < len(r) and r[i_com]:
            d["comprador"] = str(r[i_com]).strip()
        if i_tipo is not None and i_tipo < len(r) and r[i_tipo]:
            d["tipo"] = str(r[i_tipo]).strip()

    db.execute(delete(DespachoContratoMensual).where(DespachoContratoMensual.periodo == per))
    for con, d in agg.items():
        db.add(DespachoContratoMensual(
            periodo=per, codigo_sic_contrato=con, kwh=round(d["kwh"], 4),
            vendedor=d["vendedor"], comprador=d["comprador"], tipo=d["tipo"],
            archivo=archivo.filename,
        ))
    db.commit()
    total = sum(d["kwh"] for d in agg.values())
    return {"periodo": per, "contratos": len(agg), "kwh_total": round(total, 2), "archivo": archivo.filename}


@router.get("/despacho")
def listar_despacho(periodo: str = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    per = _norm_periodo(periodo)
    rows = (
        db.query(DespachoContratoMensual)
        .filter(DespachoContratoMensual.periodo == per)
        .order_by(DespachoContratoMensual.codigo_sic_contrato).all()
    )
    return {
        "periodo": per,
        "kwh_total": round(sum(float(r.kwh) for r in rows), 2),
        "contratos": [
            {"contrato": r.codigo_sic_contrato, "vendedor": r.vendedor, "comprador": r.comprador,
             "tipo": r.tipo, "kwh": float(r.kwh)} for r in rows
        ],
        "archivo": rows[0].archivo if rows else None,
    }


# ── Cálculo de facturación ─────────────────────────────────────────────────────
def _facturacion_periodo(db: Session, per: str) -> dict:
    y, m = per.split("-")
    año, mes = int(y), int(m)

    despacho = db.query(DespachoContratoMensual).filter(DespachoContratoMensual.periodo == per).all()
    ipp_row = db.query(IppMensual).filter(IppMensual.año == año, IppMensual.mes == mes).first()
    ipp = float(ipp_row.valor) if ipp_row else None

    # contrato XM → solicitud asic VIGENTE al fin del período (resolver_vigencias
    # corre sobre el universo publicado, igual que la vista de asic).
    last_day = date(año, mes, monthrange(año, mes)[1])
    universo = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud != TipoSolicitudAsicEnum.desistimiento,
        )
        .order_by(
            AsicSolicitud.fecha_inicio.asc().nullsfirst(),
            AsicSolicitud.fecha_solicitud.asc().nullsfirst(),
            AsicSolicitud.created_at.asc(),
        ).all()
    )
    vig = resolver_vigencias(universo, hasta=last_day)
    sol: dict = {}
    for s in universo:
        v = vig.get(s.id)
        if v is not None and v.vigente:
            c = (s.codigo_sic_contrato or "").strip()
            if c:
                sol[c] = s
    ppas = {p.id: p for p in db.query(PPAContrato).all()}
    tarifas: dict = {}
    for t in db.query(PPATarifa).filter(PPATarifa.año == año, PPATarifa.mes == mes).all():
        tarifas[t.contrato_id] = float(t.tarifa) if t.tarifa is not None else None
    proy_nombre = {pid: nom for pid, nom in db.query(Proyecto.id, Proyecto.nombre_comercial).all()}

    lineas = []
    for d in despacho:
        c = d.codigo_sic_contrato
        kwh = float(d.kwh)
        s = sol.get(c)
        pid = s.contrato_ppa_id if s else None
        proyid = s.proyecto_id if s else None
        ppa = ppas.get(pid) if pid else None
        base = tarifas.get(pid) if pid else None
        ipp_base = float(ppa.valor_indexacion_base) if (ppa and ppa.valor_indexacion_base) else None

        estado = "ok"
        tarifa_idx = fact = None
        if not pid:
            estado = "sin_ppa"
        elif base is None:
            estado = "sin_tarifa"
        elif not ipp_base:
            estado = "sin_ipp_base"
        elif ipp is None:
            estado = "sin_ipp_mes"
        else:
            tarifa_idx = round(base * ipp / ipp_base, 2)   # redondeo idéntico al Excel
            fact = round(kwh * tarifa_idx, 2)
        lineas.append({
            "contrato": c,
            "comprador": d.comprador,
            "proyecto_id": proyid,
            "proyecto": proy_nombre.get(proyid) if proyid else None,
            "ppa": (ppa.nombre_interno or ppa.numero_codigo_contrato) if ppa else None,
            "kwh": kwh,
            "tarifa_base": base,
            "ipp_base": ipp_base,
            "ipp_mes": ipp,
            "tarifa_indexada": tarifa_idx,
            "facturacion": fact,
            "estado": estado,
        })

    def _suma(rows):
        return round(sum(r["facturacion"] or 0 for r in rows), 2)
    facturables = [l for l in lineas if l["estado"] == "ok"]

    # Agrupación por comprador (código SIC).
    por_sic: dict = {}
    for l in facturables:
        k = l["comprador"] or "—"
        g = por_sic.setdefault(k, {"comprador": k, "kwh": 0.0, "facturacion": 0.0, "contratos": 0})
        g["kwh"] += l["kwh"]; g["facturacion"] += l["facturacion"]; g["contratos"] += 1
    for g in por_sic.values():
        g["kwh"] = round(g["kwh"], 2); g["facturacion"] = round(g["facturacion"], 2)

    return {
        "periodo": per,
        "ipp_mes": ipp,
        "resumen": {
            "contratos": len(lineas),
            "facturables": len(facturables),
            "sin_ppa": sum(1 for l in lineas if l["estado"] == "sin_ppa"),
            "kwh_total": round(sum(l["kwh"] for l in facturables), 2),
            "facturacion_total": _suma(facturables),
        },
        "lineas": lineas,
        "por_codigo_sic": sorted(por_sic.values(), key=lambda x: -x["facturacion"]),
    }


@router.get("")
def facturacion(periodo: str = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _facturacion_periodo(db, _norm_periodo(periodo))
