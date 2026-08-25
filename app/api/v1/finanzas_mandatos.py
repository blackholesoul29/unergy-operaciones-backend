"""API del modulo Mandatos (Finanzas). Ingesta desde el script + lecturas."""
from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.finanzas_mandatos import FinanzasMandato
from app.services import finanzas_mandatos_service as svc
from app.services.finanzas_mandatos_drive import subir_pdf

router = APIRouter(prefix="/finanzas/mandatos", tags=["Finanzas - Mandatos"])


def _to_dict(m: FinanzasMandato) -> dict:
    return {
        "id": m.id, "proyecto": m.proyecto, "tercero": m.tercero,
        "periodo": m.periodo.strftime("%Y-%m") if m.periodo else None,
        "tipo": m.tipo, "cmu": m.cmu, "cmu_anterior": m.cmu_anterior,
        "estado": m.estado, "comentario": m.comentario,
        "fecha_envio": m.fecha_envio.isoformat() if m.fecha_envio else None,
        "fecha_firma": m.fecha_firma.isoformat() if m.fecha_firma else None,
        "drive_url": m.drive_url,
    }


@router.post("/ingest")
async def ingest(
    proyecto: str = Form(...), tercero: str = Form(""), periodo: str = Form(...),
    tipo: str = Form(...), estado: str = Form(...), cmu: str = Form(None),
    comentario: str = Form(None), correo_ref: str = Form(None), fecha: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")
    f = datetime.strptime(fecha[:10], "%Y-%m-%d").date() if fecha else None

    drive_id = drive_url = None
    if file is not None and estado == "firmado":
        contenido = await file.read()
        sub = f"{per.strftime('%Y-%m')}-{tipo}"
        res = subir_pdf(contenido, file.filename or f"{cmu or 'mandato'}.pdf", sub)
        drive_id, drive_url = res["id"], res["url"]

    m, creado = svc.upsert_mandato(
        db, proyecto=proyecto.strip(), tercero=tercero.strip(), periodo=per,
        tipo=tipo, cmu=svc.extraer_cmu(cmu) if cmu else None, estado=estado,
        comentario=comentario, fecha=f, correo_ref=correo_ref,
        drive_file_id=drive_id, drive_url=drive_url)
    db.commit()
    return {"ok": True, "creado": creado, "mandato": _to_dict(m)}


@router.get("")
def listar(periodo: str = Query(...), tipo: str = Query(None),
           db: Session = Depends(get_db), _=Depends(get_current_user)):
    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")
    q = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per)
    if tipo:
        q = q.filter(FinanzasMandato.tipo == tipo)
    filas = q.order_by(FinanzasMandato.proyecto, FinanzasMandato.tercero).all()
    return {"periodo": periodo, "mandatos": [_to_dict(m) for m in filas]}


@router.get("/resumen")
def resumen(periodo: str = Query(...), db: Session = Depends(get_db),
            _=Depends(get_current_user)):
    per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    filas = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per).all()
    def conteo(tp):
        sub = [m for m in filas if m.tipo == tp]
        return {
            "total": len(sub),
            "firmados": sum(1 for m in sub if m.estado == "firmado"),
            "falta_firma": sum(1 for m in sub if m.estado == "sin_firma"),
            "con_comentarios": sum(1 for m in sub if m.estado == "con_comentarios"),
        }
    return {"periodo": periodo, "ingreso": conteo("ingreso"), "costo": conteo("costo")}


@router.get("/reconciliacion")
def reconciliacion(periodo: str = Query(...), tipo: str = Query(None),
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    """De los mandatos enviados en el período, cuáles no han vuelto."""
    from app.services.mandatos.reconciliacion import reconciliar

    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")

    q = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per)
    if tipo:
        q = q.filter(FinanzasMandato.tipo == tipo)
    return {"periodo": periodo, "tipo": tipo, **reconciliar(q.all())}
