"""
API del panel O&M mensual.

Endpoints:
  GET  /om/proyectos                              → lista contratos mantenimiento
  GET  /om/calculo/{periodo}                      → calcula valores para el período
  GET  /om/seleccion/{periodo}                    → obtiene selección guardada
  POST /om/seleccion/{periodo}                    → guarda selección mensual
  PATCH /om/seleccion/{periodo}/{contrato_id}/facturado  → toggle facturado
  GET  /om/ipc                                    → lista tasas IPC
  PUT  /om/ipc/{año}                             → crea/actualiza tasa IPC
  GET  /om/ipc/pendiente                          → tasa sugerida (Banrep fallback)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.contratos import ContratoServicio
from app.models.om import IPCTasa, OMSeleccion
from app.schemas.om import (
    IPCTasaOut, IPCTasaUpsert,
    OMContratoOut, OMCalculoFila, OMCalculoResponse,
    OMSeleccionGuardar, OMSeleccionOut,
)
from app.services.om_calculator import calcular_proyecto

router = APIRouter(prefix="/om", tags=["OM Mensual"])


# ── Proyectos / contratos ────────────────────────────────────────────────────

@router.get("/proyectos", response_model=list[OMContratoOut])
def listar_contratos_om(
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lista todos los contratos de mantenimiento."""
    contratos = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento")
        .order_by(ContratoServicio.id)
        .all()
    )
    result = []
    for c in contratos:
        nombre = (
            c.proyecto.nombre_comercial
            if c.proyecto else
            c.prestador_nombre or f"Contrato #{c.id}"
        )
        result.append(OMContratoOut(
            contrato_id=c.id,
            proyecto_id=c.proyecto_id,
            nombre_proyecto=nombre,
            fecha_inicio=c.fecha_inicio,
            valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
            estado=c.estado or "vigente",
        ))
    return result


# ── Cálculo mensual ──────────────────────────────────────────────────────────

@router.get("/calculo/{periodo}", response_model=OMCalculoResponse)
def calcular_periodo(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Calcula valores O&M para todos los contratos en el período dado.
    periodo formato: YYYY-MM (e.g. "2026-06")
    """
    try:
        año, mes = periodo.split("-")
        assert 1 <= int(mes) <= 12
    except Exception:
        raise HTTPException(400, "periodo debe tener formato YYYY-MM")

    tasas_rows = db.query(IPCTasa).all()
    ipc_tasas = {r.año: float(r.tasa) for r in tasas_rows}

    selecciones = {
        s.contrato_id: s
        for s in db.query(OMSeleccion).filter(OMSeleccion.periodo == periodo).all()
    }

    contratos = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento")
        .order_by(ContratoServicio.id)
        .all()
    )

    filas = []
    total = 0

    for c in contratos:
        nombre = (
            c.proyecto.nombre_comercial
            if c.proyecto else
            c.prestador_nombre or f"Contrato #{c.id}"
        )
        sel = selecciones.get(c.id)
        incluido = sel.incluido if sel else True
        facturado = sel.facturado if sel else False

        fila_data = calcular_proyecto(
            contrato_id=c.id,
            nombre_proyecto=nombre,
            fecha_inicio=c.fecha_inicio,
            valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
            periodo=periodo,
            ipc_tasas=ipc_tasas,
            incluido=incluido,
            facturado=facturado,
        )
        fila = OMCalculoFila(**fila_data)
        filas.append(fila)

        if fila.incluido and fila.habilitado and fila.valor_a_facturar:
            total += fila.valor_a_facturar

    return OMCalculoResponse(periodo=periodo, filas=filas, total_seleccionado=total)


# ── Selección mensual ────────────────────────────────────────────────────────

@router.get("/seleccion/{periodo}", response_model=list[OMSeleccionOut])
def obtener_seleccion(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return db.query(OMSeleccion).filter(OMSeleccion.periodo == periodo).all()


@router.post("/seleccion/{periodo}", response_model=list[OMSeleccionOut])
def guardar_seleccion(
    periodo: str,
    payload: OMSeleccionGuardar,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Guarda / actualiza la selección de contratos para el período (upsert)."""
    resultados = []
    for item in payload.items:
        sel = db.query(OMSeleccion).filter(
            OMSeleccion.contrato_id == item.contrato_id,
            OMSeleccion.periodo == periodo,
        ).first()

        if sel:
            sel.incluido = item.incluido
        else:
            sel = OMSeleccion(
                contrato_id=item.contrato_id,
                periodo=periodo,
                incluido=item.incluido,
                facturado=False,
            )
            db.add(sel)
        resultados.append(sel)

    db.commit()
    for s in resultados:
        db.refresh(s)
    return resultados


@router.patch("/seleccion/{periodo}/{contrato_id}/facturado", response_model=OMSeleccionOut)
def toggle_facturado(
    periodo: str,
    contrato_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Marca/desmarca un contrato como facturado para el período."""
    sel = db.query(OMSeleccion).filter(
        OMSeleccion.contrato_id == contrato_id,
        OMSeleccion.periodo == periodo,
    ).first()

    if not sel:
        sel = OMSeleccion(contrato_id=contrato_id, periodo=periodo, incluido=True, facturado=True)
        db.add(sel)
    else:
        sel.facturado = not sel.facturado

    db.commit()
    db.refresh(sel)
    return sel


# ── IPC ──────────────────────────────────────────────────────────────────────

@router.get("/ipc", response_model=list[IPCTasaOut])
def listar_ipc(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(IPCTasa).order_by(IPCTasa.año).all()


@router.put("/ipc/{año}", response_model=IPCTasaOut)
def upsert_ipc(
    año: int,
    payload: IPCTasaUpsert,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Crea o actualiza la tasa IPC de un año."""
    tasa = db.query(IPCTasa).filter(IPCTasa.año == año).first()
    if tasa:
        tasa.tasa       = payload.tasa
        tasa.confirmado = payload.confirmado
        tasa.fuente     = payload.fuente
    else:
        tasa = IPCTasa(año=año, tasa=payload.tasa, confirmado=payload.confirmado, fuente=payload.fuente)
        db.add(tasa)
    db.commit()
    db.refresh(tasa)
    return tasa


@router.get("/ipc/pendiente")
def ipc_pendiente(_=Depends(get_current_user)):
    """
    Consulta el IPC del año anterior desde el Banco de la República.
    Por ahora devuelve None (fallback manual) — la integración Banrep queda para mejora futura.
    """
    from datetime import datetime
    año_consulta = datetime.now().year - 1
    return {"año": año_consulta, "tasa_sugerida": None, "fuente": "manual"}
