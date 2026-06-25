"""API del panel de Arriendos (mirror de om.py)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.arriendos import ArrProyecto, ArrIPCTasa, ArrSeleccion
from app.schemas.arriendos import (
    ArrIPCOut, ArrIPCUpsert, ArrProyectoIn, ArrProyectoOut,
    ArrCalculoFila, ArrCalculoResponse,
    ArrSeleccionGuardar, ArrSeleccionOut,
)
from app.services.arr_calculator import calcular_arriendo

router = APIRouter(prefix="/arriendos", tags=["Arriendos"])


def _validar_periodo(periodo: str):
    try:
        _, mes = periodo.split("-")
        assert 1 <= int(mes) <= 12
    except Exception:
        raise HTTPException(400, "periodo debe tener formato YYYY-MM")


@router.get("/calculo/{periodo}", response_model=ArrCalculoResponse)
def calcular_periodo(periodo: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _validar_periodo(periodo)
    ipc_tasas = {r.año: float(r.tasa) for r in db.query(ArrIPCTasa).all()}
    selecciones = {s.arr_proyecto_id: s
                   for s in db.query(ArrSeleccion).filter(ArrSeleccion.periodo == periodo).all()}
    proyectos = db.query(ArrProyecto).filter(ArrProyecto.activo == True).order_by(ArrProyecto.id).all()  # noqa: E712

    filas, total = [], 0
    for p in proyectos:
        sel = selecciones.get(p.id)
        fila = ArrCalculoFila(**calcular_arriendo(
            proyecto_id=p.id, nombre=p.nombre, codigo=p.codigo,
            fecha_firma_contrato=p.fecha_firma_contrato,
            valor_base=float(p.valor_base) if p.valor_base is not None else None,
            canon_archivo=float(p.canon_archivo) if p.canon_archivo is not None else None,
            periodo=periodo, ipc_tasas=ipc_tasas,
            incluido=(sel.incluido if sel else True),
            facturado=(sel.facturado if sel else False),
        ))
        filas.append(fila)
        if fila.incluido and fila.habilitado and fila.canon_a_facturar:
            total += fila.canon_a_facturar
    return ArrCalculoResponse(periodo=periodo, filas=filas, total_seleccionado=total)


@router.get("/proyectos", response_model=list[ArrProyectoOut])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ArrProyecto).order_by(ArrProyecto.id).all()


@router.post("/proyectos", response_model=ArrProyectoOut)
def crear_proyecto(payload: ArrProyectoIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = ArrProyecto(**payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p


@router.put("/proyectos/{proyecto_id}", response_model=ArrProyectoOut)
def editar_proyecto(proyecto_id: int, payload: ArrProyectoIn, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(ArrProyecto).filter(ArrProyecto.id == proyecto_id).first()
    if not p:
        raise HTTPException(404, "proyecto no encontrado")
    for k, v in payload.model_dump().items():
        setattr(p, k, v)
    db.commit(); db.refresh(p)
    return p


@router.get("/seleccion/{periodo}", response_model=list[ArrSeleccionOut])
def obtener_seleccion(periodo: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ArrSeleccion).filter(ArrSeleccion.periodo == periodo).all()


@router.post("/seleccion/{periodo}", response_model=list[ArrSeleccionOut])
def guardar_seleccion(periodo: str, payload: ArrSeleccionGuardar, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _validar_periodo(periodo)
    res = []
    for item in payload.items:
        sel = db.query(ArrSeleccion).filter(
            ArrSeleccion.arr_proyecto_id == item.proyecto_id,
            ArrSeleccion.periodo == periodo,
        ).first()
        if sel:
            sel.incluido = item.incluido
        else:
            sel = ArrSeleccion(arr_proyecto_id=item.proyecto_id, periodo=periodo,
                               incluido=item.incluido, facturado=False)
            db.add(sel)
        res.append(sel)
    db.commit()
    for s in res:
        db.refresh(s)
    return res


@router.patch("/seleccion/{periodo}/{proyecto_id}/facturado", response_model=ArrSeleccionOut)
def toggle_facturado(periodo: str, proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    sel = db.query(ArrSeleccion).filter(
        ArrSeleccion.arr_proyecto_id == proyecto_id, ArrSeleccion.periodo == periodo,
    ).first()
    if not sel:
        sel = ArrSeleccion(arr_proyecto_id=proyecto_id, periodo=periodo, incluido=True, facturado=True)
        db.add(sel)
    else:
        sel.facturado = not sel.facturado
    db.commit(); db.refresh(sel)
    return sel


@router.get("/ipc", response_model=list[ArrIPCOut])
def listar_ipc(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(ArrIPCTasa).order_by(ArrIPCTasa.año).all()


@router.put("/ipc/{año}", response_model=ArrIPCOut)
def upsert_ipc(año: int, payload: ArrIPCUpsert, db: Session = Depends(get_db), _=Depends(get_current_user)):
    t = db.query(ArrIPCTasa).filter(ArrIPCTasa.año == año).first()
    if t:
        t.tasa = payload.tasa; t.confirmado = payload.confirmado; t.fuente = payload.fuente
    else:
        t = ArrIPCTasa(año=año, tasa=payload.tasa, confirmado=payload.confirmado, fuente=payload.fuente)
        db.add(t)
    db.commit(); db.refresh(t)
    return t
