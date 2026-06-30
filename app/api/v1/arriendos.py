"""API del panel de Arriendos (mirror de om.py)."""
from __future__ import annotations
import json
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.arriendos import ArrProyecto, ArrIPCTasa, ArrSeleccion, ArrDocumento

_UPLOADS_DIR = _Path(__file__).parent.parent.parent.parent / "uploads" / "arriendos"
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


# ── Documentos de arriendo ────────────────────────────────────────────────────

@router.get("/documentos/{periodo}")
def listar_documentos_periodo(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Devuelve todos los documentos de arriendo guardados para un período."""
    docs = (
        db.query(ArrDocumento)
        .filter(ArrDocumento.periodo == periodo)
        .order_by(ArrDocumento.arr_proyecto_id, ArrDocumento.pago_id)
        .all()
    )
    return [
        {
            "id":                 d.id,
            "arr_proyecto_id":    d.arr_proyecto_id,
            "periodo":            d.periodo,
            "pago_id":            d.pago_id,
            "codigo_contrato":    d.codigo_contrato,
            "tipo_documento":     d.tipo_documento,
            "nombre_archivo":     d.nombre_archivo,
            "nombre_secundario":  d.nombre_secundario,
            "codigo_predio":       d.codigo_predio,
            "numero_cuenta_cobro": d.numero_cuenta_cobro,
            "nombre_arrendatario": d.nombre_arrendatario,
            "valor_individual":    float(d.valor_individual) if d.valor_individual is not None else None,
            "fecha_subida":       d.fecha_subida,
        }
        for d in docs
    ]


@router.post("/documentos/upload")
async def upload_documento(
    arr_proyecto_id:  int = Form(...),
    periodo:          str = Form(...),
    pago_id:          int = Form(...),
    codigo_contrato:  str = Form(...),
    tipo_documento:   str = Form(...),
    nombre_resultante:str = Form(...),
    file:             UploadFile = File(...),
    file_secundario:  UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Sube un documento de arriendo (principal + opcional secundario) y lo registra en BD."""
    _validar_periodo(periodo)

    directorio = _UPLOADS_DIR / periodo / codigo_contrato
    directorio.mkdir(parents=True, exist_ok=True)

    # Guardar archivo principal
    ext_principal = _Path(file.filename or "doc.pdf").suffix or ".pdf"
    nombre_archivo = nombre_resultante if nombre_resultante.endswith(ext_principal) else nombre_resultante
    ruta_principal = directorio / nombre_archivo
    ruta_principal.write_bytes(await file.read())

    # Guardar archivo secundario si existe
    nombre_sec = None
    ruta_sec   = None
    if file_secundario and file_secundario.filename:
        ext_sec   = _Path(file_secundario.filename).suffix or ".pdf"
        nombre_sec = f"{nombre_resultante.rsplit('.', 1)[0]}_enviada{ext_sec}"
        ruta_obj   = directorio / nombre_sec
        ruta_obj.write_bytes(await file_secundario.read())
        ruta_sec = str(ruta_obj)

    # Upsert en BD (misma clave: proyecto + período + pago_id)
    doc = db.query(ArrDocumento).filter(
        ArrDocumento.arr_proyecto_id == arr_proyecto_id,
        ArrDocumento.periodo         == periodo,
        ArrDocumento.pago_id         == pago_id,
    ).first()

    if doc:
        doc.codigo_contrato   = codigo_contrato
        doc.tipo_documento    = tipo_documento
        doc.nombre_archivo    = nombre_archivo
        doc.ruta_local        = str(ruta_principal)
        doc.nombre_secundario = nombre_sec
        doc.ruta_secundario   = ruta_sec
    else:
        doc = ArrDocumento(
            arr_proyecto_id=arr_proyecto_id,
            periodo=periodo,
            pago_id=pago_id,
            codigo_contrato=codigo_contrato,
            tipo_documento=tipo_documento,
            nombre_archivo=nombre_archivo,
            ruta_local=str(ruta_principal),
            nombre_secundario=nombre_sec,
            ruta_secundario=ruta_sec,
        )
        db.add(doc)

    db.commit()
    db.refresh(doc)
    return {"ok": True, "id": doc.id, "nombre_archivo": doc.nombre_archivo}


@router.post("/documentos/upload-cuenta-cobro")
async def upload_cuenta_cobro(
    periodo:             str = Form(...),
    pago_id:             int = Form(...),
    codigo_contrato:     str = Form(...),
    tipo_documento:      str = Form(...),
    predios:             str = Form(...),   # JSON: [{arr_proyecto_id|null, codigo_predio, valor_individual, nombre_resultante}]
    numero_cuenta_cobro: str | None = Form(None),
    nombre_arrendatario: str | None = Form(None),
    file:                UploadFile = File(...),
    file_secundario:     UploadFile | None = File(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Sube UN documento (cuenta de cobro/factura) y genera UNA COPIA RENOMBRADA por predio.

    Por cada predio recibido se escribe una copia del archivo con su nombre_resultante
    propio ([PREDIO]_[YYYY-MM]_[Arrendatario]_[Proyecto].pdf) y se crea/actualiza una
    fila ArrDocumento. Los predios sin match (arr_proyecto_id null) también se guardan
    para revisión manual. El archivo original se conserva una sola vez como referencia.
    """
    _validar_periodo(periodo)

    try:
        lista_predios = json.loads(predios)
        assert isinstance(lista_predios, list) and lista_predios
    except Exception:
        raise HTTPException(400, "predios debe ser un JSON array no vacío")

    directorio = _UPLOADS_DIR / periodo / codigo_contrato
    directorio.mkdir(parents=True, exist_ok=True)

    # Leer el archivo principal una sola vez (se copia por cada predio)
    contenido = await file.read()

    # Conservar el original sin renombrar (una sola copia de referencia)
    ext_orig      = _Path(file.filename or "documento.pdf").suffix or ".pdf"
    nombre_orig   = f"_original_pago{pago_id}{ext_orig}"
    ruta_original = directorio / nombre_orig
    ruta_original.write_bytes(contenido)

    # Guardar secundario (enviada) una sola vez
    nombre_sec = None
    ruta_sec   = None
    if file_secundario and file_secundario.filename:
        ext_sec    = _Path(file_secundario.filename).suffix or ".pdf"
        nombre_sec = f"_enviada_pago{pago_id}{ext_sec}"
        ruta_obj   = directorio / nombre_sec
        ruta_obj.write_bytes(await file_secundario.read())
        ruta_sec   = str(ruta_obj)

    def _sanit(nombre: str) -> str:
        limpio = "".join(c for c in nombre if c not in '/\\:*?"<>|').strip()
        return limpio or f"documento_pago{pago_id}.pdf"

    asociados = 0
    sin_match = 0
    for p in lista_predios:
        codigo_predio = p.get("codigo_predio")
        valor         = p.get("valor_individual")
        try:
            arr_proyecto_id = int(p["arr_proyecto_id"]) if p.get("arr_proyecto_id") is not None else None
        except (TypeError, ValueError):
            arr_proyecto_id = None

        # Nombre de archivo: usar el que envía el front; si falta, construirlo completo
        # ([PREDIO]_[YYYY-MM]_[Arrendatario]_[Proyecto].pdf) desde BD como respaldo.
        nombre_resultante = p.get("nombre_resultante")
        if not nombre_resultante:
            proy_nombre = None
            if arr_proyecto_id is not None:
                ap = db.query(ArrProyecto).filter(ArrProyecto.id == arr_proyecto_id).first()
                proy_nombre = ap.nombre if ap else None
            partes = [codigo_predio or "predio", periodo]
            if nombre_arrendatario:
                partes.append(nombre_arrendatario)
            partes.append(proy_nombre or "SIN-MATCH")
            nombre_resultante = "_".join(partes) + ".pdf"
        nombre_arch = _sanit(str(nombre_resultante))

        # Escribir la copia renombrada de este predio
        ruta_copia = directorio / nombre_arch
        ruta_copia.write_bytes(contenido)

        # Predios con match: upsert por (proyecto, período, pago). Sin match: siempre insert.
        doc = None
        if arr_proyecto_id is not None:
            doc = db.query(ArrDocumento).filter(
                ArrDocumento.arr_proyecto_id == arr_proyecto_id,
                ArrDocumento.periodo         == periodo,
                ArrDocumento.pago_id         == pago_id,
            ).first()
        if not doc:
            doc = ArrDocumento(arr_proyecto_id=arr_proyecto_id, periodo=periodo, pago_id=pago_id)
            db.add(doc)

        doc.codigo_contrato     = codigo_contrato
        doc.tipo_documento      = tipo_documento
        doc.nombre_archivo      = nombre_arch
        doc.ruta_local          = str(ruta_copia)
        doc.ruta_original       = str(ruta_original)
        doc.nombre_secundario   = nombre_sec
        doc.ruta_secundario     = ruta_sec
        doc.codigo_predio       = codigo_predio
        doc.numero_cuenta_cobro = numero_cuenta_cobro
        doc.nombre_arrendatario = nombre_arrendatario
        doc.valor_individual    = valor
        if arr_proyecto_id is not None:
            asociados += 1
        else:
            sin_match += 1

    db.commit()
    return {"ok": True, "predios_asociados": asociados, "predios_sin_match": sin_match,
            "copias_generadas": asociados + sin_match}


@router.get("/documentos/file/{doc_id}", response_class=FileResponse)
def download_documento(
    doc_id: int,
    secundario: bool = False,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Descarga el PDF de un documento de arriendo."""
    doc = db.query(ArrDocumento).filter(ArrDocumento.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")

    ruta_raw = doc.ruta_secundario if secundario else doc.ruta_local
    if not ruta_raw:
        raise HTTPException(404, "Archivo no disponible")

    file_path = _Path(ruta_raw).resolve()
    if not str(file_path).startswith(str(_UPLOADS_DIR.resolve())):
        raise HTTPException(403, "Acceso denegado")
    if not file_path.exists():
        raise HTTPException(404, "Archivo no encontrado en el servidor")

    filename = doc.nombre_secundario if secundario else doc.nombre_archivo
    return FileResponse(path=str(file_path), filename=filename, media_type="application/pdf")


@router.delete("/documentos/{doc_id}")
def eliminar_documento(
    doc_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Elimina un documento de arriendo (registro BD; el archivo en disco permanece)."""
    doc = db.query(ArrDocumento).filter(ArrDocumento.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "Documento no encontrado")
    db.delete(doc)
    db.commit()
    return {"ok": True}
