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
from app.models.om import IPCTasa, OMSeleccion, OMFacturaMensual, OMDocumentoProyecto
from app.schemas.om import (
    IPCTasaOut, IPCTasaUpsert,
    OMContratoOut, OMCalculoFila, OMCalculoResponse,
    OMSeleccionGuardar, OMSeleccionOut,
)
from app.services.om_calculator import calcular_proyecto
from app.services.om_pdf_splitter import dividir_pdf

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

    # Documentos por proyecto para este período
    documentos_ids = {
        d.contrato_id
        for d in db.query(OMDocumentoProyecto)
            .filter(OMDocumentoProyecto.periodo == periodo)
            .all()
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
        valor_manual = float(sel.valor_manual) if sel and sel.valor_manual is not None else None

        fila_data = calcular_proyecto(
            contrato_id=c.id,
            nombre_proyecto=nombre,
            fecha_firma_contrato=c.fecha_firma_contrato,
            fecha_inicio_om=c.fecha_inicio_om,
            valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
            periodo=periodo,
            ipc_tasas=ipc_tasas,
            incluido=incluido,
            facturado=facturado,
            valor_manual=valor_manual,
        )
        fila_data["documento_disponible"] = c.id in documentos_ids
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
            sel.valor_manual = item.valor_manual
        else:
            sel = OMSeleccion(
                contrato_id=item.contrato_id,
                periodo=periodo,
                incluido=item.incluido,
                facturado=False,
                valor_manual=item.valor_manual,
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


# ── Factura consolidada mensual del proveedor ─────────────────────────────────

from pathlib import Path as _Path
from fastapi import UploadFile, File
from fastapi.responses import FileResponse

_UPLOADS_DIR = _Path(__file__).parent.parent.parent.parent / "uploads" / "om"


@router.get("/factura/{periodo}")
def get_factura_mensual(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Devuelve info de la factura consolidada del período."""
    factura = db.query(OMFacturaMensual).filter(OMFacturaMensual.periodo == periodo).first()
    if not factura:
        return {"periodo": periodo, "nombre_archivo": None, "enlace_pdf": None,
                "tiene_archivo": False, "subido_en": None}
    tiene_archivo = bool(
        factura.ruta_local and _Path(factura.ruta_local).exists()
    )
    return {
        "periodo":        periodo,
        "nombre_archivo": factura.nombre_archivo,
        "enlace_pdf":     factura.enlace_pdf,
        "tiene_archivo":  tiene_archivo,
        "subido_en":      factura.subido_en,
    }


@router.post("/factura/{periodo}/upload")
async def upload_factura_mensual(
    periodo: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Recibe el PDF consolidado, lo guarda y lo divide por proyecto."""
    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    ext = _Path(file.filename or "factura.pdf").suffix or ".pdf"
    safe_name = f"{periodo}{ext}"
    file_path = _UPLOADS_DIR / safe_name

    content = await file.read()
    file_path.write_bytes(content)

    # Guardar/actualizar registro de factura consolidada
    factura = db.query(OMFacturaMensual).filter(OMFacturaMensual.periodo == periodo).first()
    if factura:
        factura.nombre_archivo = file.filename
        factura.ruta_local     = str(file_path)
        factura.enlace_pdf     = None
    else:
        factura = OMFacturaMensual(
            periodo=periodo,
            nombre_archivo=file.filename,
            ruta_local=str(file_path),
        )
        db.add(factura)
    db.flush()  # persiste en transacción sin commit aún

    # ── División por proyecto ────────────────────────────────────────────────
    contratos = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento")
        .all()
    )
    contratos_lista = [
        {
            "contrato_id": c.id,
            "nombre_proyecto": (
                c.proyecto.nombre_comercial if c.proyecto
                else c.prestador_nombre or f"Contrato #{c.id}"
            ),
        }
        for c in contratos
    ]

    directorio_docs = _UPLOADS_DIR / "documentos" / periodo
    try:
        splitting_result = dividir_pdf(file_path, periodo, contratos_lista, directorio_docs)
    except Exception as exc:
        db.commit()  # guardar la factura aunque el split falle
        return {
            "ok": True,
            "nombre_archivo": file.filename,
            "periodo": periodo,
            "splitting_result": {
                "procesados": 0,
                "sin_match": [],
                "detalle": [],
                "error": str(exc),
            },
        }

    for item in splitting_result["procesados"]:
        doc = db.query(OMDocumentoProyecto).filter(
            OMDocumentoProyecto.contrato_id == item["contrato_id"],
            OMDocumentoProyecto.periodo == periodo,
        ).first()
        if doc:
            doc.nombre_archivo      = item["archivo"]
            doc.ruta_local          = item["ruta_local"]
            doc.numero_factura      = item.get("numero_factura")
            doc.total_sin_impuestos = item.get("total_sin_impuestos")
            doc.iva                 = item.get("iva")
            doc.total_pagar         = item.get("total_pagar")
            doc.fecha_facturacion   = item.get("fecha_facturacion")
            doc.cufe                = item.get("cufe")
        else:
            doc = OMDocumentoProyecto(
                contrato_id=item["contrato_id"],
                periodo=periodo,
                nombre_archivo=item["archivo"],
                ruta_local=item["ruta_local"],
                numero_factura=item.get("numero_factura"),
                total_sin_impuestos=item.get("total_sin_impuestos"),
                iva=item.get("iva"),
                total_pagar=item.get("total_pagar"),
                fecha_facturacion=item.get("fecha_facturacion"),
                cufe=item.get("cufe"),
            )
            db.add(doc)
    db.commit()  # commit único para factura + documentos

    return {
        "ok": True,
        "nombre_archivo": file.filename,
        "periodo": periodo,
        "splitting_result": {
            "procesados": len(splitting_result["procesados"]),
            "sin_match": splitting_result["sin_match"],
            "detalle": splitting_result["procesados"],
        },
    }


@router.put("/factura/{periodo}/enlace")
def set_enlace_factura(
    periodo: str,
    payload: dict,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Guarda un link externo (Drive, etc.) como factura consolidada del período."""
    factura = db.query(OMFacturaMensual).filter(OMFacturaMensual.periodo == periodo).first()
    if factura:
        factura.enlace_pdf     = payload.get("enlace_pdf")
        factura.nombre_archivo = payload.get("nombre_archivo") or payload.get("enlace_pdf")
        factura.ruta_local     = None
    else:
        factura = OMFacturaMensual(
            periodo=periodo,
            enlace_pdf=payload.get("enlace_pdf"),
            nombre_archivo=payload.get("nombre_archivo") or payload.get("enlace_pdf"),
        )
        db.add(factura)
    db.commit()
    return {"ok": True}


@router.get("/documento/{periodo}/{contrato_id}", response_class=FileResponse)
def download_documento_proyecto(
    periodo: str,
    contrato_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Descarga el PDF individual de un proyecto para el período dado."""
    doc = db.query(OMDocumentoProyecto).filter(
        OMDocumentoProyecto.periodo == periodo,
        OMDocumentoProyecto.contrato_id == contrato_id,
    ).first()
    if not doc:
        raise HTTPException(404, "No hay documento para este proyecto y período")
    file_path = _Path(doc.ruta_local).resolve()
    if not str(file_path).startswith(str(_UPLOADS_DIR.resolve())):
        raise HTTPException(403, "Acceso denegado")
    if not file_path.exists():
        raise HTTPException(404, "Archivo no encontrado en el servidor")
    return FileResponse(
        path=str(file_path),
        filename=doc.nombre_archivo,
        media_type="application/pdf",
    )


@router.get("/factura/{periodo}/file")
def download_factura_mensual(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Descarga el archivo PDF guardado en el servidor."""
    factura = db.query(OMFacturaMensual).filter(OMFacturaMensual.periodo == periodo).first()
    if not factura or not factura.ruta_local:
        raise HTTPException(404, "No hay archivo subido para este período")
    file_path = _Path(factura.ruta_local)
    if not file_path.exists():
        raise HTTPException(404, "Archivo no encontrado en el servidor")
    return FileResponse(
        path=str(file_path),
        filename=factura.nombre_archivo or f"factura-{periodo}.pdf",
        media_type="application/octet-stream",
    )
