"""API del panel de Arriendos (mirror de om.py)."""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.arriendos import ArrProyecto, ArrIPCTasa, ArrSeleccion, ArrDocumento
from app.models.proyectos import Proyecto
from app.models.contratos import ContratoServicio

_UPLOADS_DIR = _Path(__file__).parent.parent.parent.parent / "uploads" / "arriendos"
from app.schemas.arriendos import (
    ArrIPCOut, ArrIPCUpsert, ArrProyectoIn, ArrProyectoOut,
    ArrCalculoFila, ArrCalculoResponse,
    ArrSeleccionGuardar, ArrSeleccionOut,
)
from app.schemas.om import OMIndexacionFila, OMIndexacionResponse
from app.services.arr_calculator import calcular_arriendo, serie_indexacion

router = APIRouter(prefix="/arriendos", tags=["Arriendos"])


def _validar_periodo(periodo: str):
    try:
        _, mes = periodo.split("-")
        assert 1 <= int(mes) <= 12
    except Exception:
        raise HTTPException(400, "periodo debe tener formato YYYY-MM")


def _safe_segment(nombre: str) -> str:
    """Sanea un componente de ruta: sin separadores ni '..' (evita path traversal)."""
    limpio = "".join(c for c in (nombre or "") if c not in '/\\:*?"<>|').replace("..", "").strip()
    return limpio or "sin_codigo"


@router.get("/calculo/{periodo}", response_model=ArrCalculoResponse)
def calcular_periodo(periodo: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Los datos de facturación (valor, fecha inicio O&M, periodicidad, estado, tipo)
    salen del contrato de arriendo en Operación (ContratoServicio servicio_aplica=
    'arriendo' ligado al Proyecto). ArrProyecto se mantiene como llave de la fila
    (selección/documentos) y como respaldo si aún no hay contrato. canon_archivo
    (override) se conserva."""
    from app.services.om_calculator import om_keys, om_match_seed

    ipc_tasas = {r.año: float(r.tasa) for r in db.query(ArrIPCTasa).all()}
    selecciones = {s.arr_proyecto_id: s
                   for s in db.query(ArrSeleccion).filter(ArrSeleccion.periodo == periodo).all()}
    arr = db.query(ArrProyecto).filter(ArrProyecto.activo == True).order_by(ArrProyecto.id).all()  # noqa: E712

    # Emparejar cada ArrProyecto con su Proyecto (difuso) y el contrato de arriendo.
    arr_keys = [(a, om_keys(a.nombre)) for a in arr]
    arr_to_proy = {}
    for p in db.query(Proyecto).all():
        a = om_match_seed(p.nombre_comercial or "", arr_keys)
        if a is not None and a.id not in arr_to_proy:
            arr_to_proy[a.id] = p
    contrato_por_proy = {}
    for c in db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "arriendo",
            ContratoServicio.proyecto_id.isnot(None)).order_by(ContratoServicio.id).all():
        contrato_por_proy.setdefault(c.proyecto_id, c)

    filas, total = [], 0
    for a in arr:
        sel = selecciones.get(a.id)
        p = arr_to_proy.get(a.id)
        c = contrato_por_proy.get(p.id) if p else None

        if c is not None:   # fuente de verdad: el contrato en Operación
            valor_base = float(c.tarifa_base) / 12 if c.tarifa_base is not None else None
            fecha_firma = c.fecha_firma_contrato
            periodicidad = c.periodicidad_pago
            estado_contrato = "con_contrato" if c.estado == "vigente" else "en_tramite"
        else:               # sin contrato aún: respaldo a los datos del ArrProyecto
            valor_base = float(a.valor_base) if a.valor_base is not None else None
            fecha_firma = a.fecha_firma_contrato
            periodicidad = None
            estado_contrato = "sin_contrato"

        data = calcular_arriendo(
            proyecto_id=a.id, nombre=(p.nombre_comercial if p else a.nombre), codigo=a.codigo,
            fecha_firma_contrato=fecha_firma,
            valor_base=valor_base,
            canon_archivo=float(a.canon_archivo) if a.canon_archivo is not None else None,
            periodo=periodo, ipc_tasas=ipc_tasas,
            incluido=(sel.incluido if sel else True),
            facturado=(sel.facturado if sel else False),
            valor_congelado=(int(sel.valor_facturado_congelado)
                             if sel and sel.valor_facturado_congelado is not None else None),
            periodicidad=periodicidad,
        )
        data["motivo_exclusion"] = sel.motivo_exclusion if sel else None
        data["tipo_proyecto"] = p.tipo_proyecto if p else None
        data["estado_contrato"] = estado_contrato
        fila = ArrCalculoFila(**data)
        filas.append(fila)
        # Solo suma al total lo facturable: con contrato, incluido, habilitado y que aplique este mes.
        if (estado_contrato == "con_contrato" and fila.incluido and fila.habilitado
                and fila.aplica_este_mes and fila.canon_a_facturar):
            total += fila.canon_a_facturar
    return ArrCalculoResponse(periodo=periodo, filas=filas, total_seleccionado=total)


@router.get("/indexacion/{contrato_id}", response_model=OMIndexacionResponse)
def indexacion_contrato(
    contrato_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Serie de indexación (anual y mensual) de un contrato de arriendo, calculada
    automáticamente con el mismo motor que el panel de Costos — año calendario
    (1-enero), usando solo el año de fecha_firma_contrato."""
    c = db.get(ContratoServicio, contrato_id)
    if c is None or c.servicio_aplica != "arriendo":
        raise HTTPException(404, "Contrato de arriendo no encontrado")

    ipc_tasas = {r.año: float(r.tasa) for r in db.query(ArrIPCTasa).all()}
    fecha_base = c.fecha_firma_contrato
    valor_base = float(c.tarifa_base) / 12 if c.tarifa_base else None

    hoy = date.today()
    serie = serie_indexacion(fecha_base, valor_base, ipc_tasas, hoy.year, hoy.month)

    anual = [OMIndexacionFila(anio=f["anio"], ipc_aplicado=f["ipc_aplicado"], valor=f["valor_anual"])
             for f in serie]
    mensual = [OMIndexacionFila(anio=f["anio"], ipc_aplicado=f["ipc_aplicado"], valor=f["valor_mensual"])
               for f in serie]
    return OMIndexacionResponse(anual=anual, mensual=mensual)


@router.get("/diagnostico-migracion")
def diagnostico_migracion(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Read-only: dimensiona la migración de ArrProyecto → contrato de arriendo.
    Empareja cada ArrProyecto con su Proyecto de forma DIFUSA (misma lógica del
    seed O&M: ignora el código MGS y compara tokens). No modifica nada."""
    from app.services.om_calculator import om_keys, om_match_seed

    arr = db.query(ArrProyecto).filter(ArrProyecto.activo == True).all()  # noqa: E712
    arr_keys = [(a, om_keys(a.nombre)) for a in arr]
    proyectos = db.query(Proyecto).all()
    proy_con_contrato_arr = {
        c.proyecto_id
        for c in db.query(ContratoServicio).filter(
            ContratoServicio.servicio_aplica == "arriendo",
            ContratoServicio.proyecto_id.isnot(None)).all()
    }

    matched_ids = set()
    con_contrato, sin_contrato = 0, []
    for p in proyectos:
        a = om_match_seed(p.nombre_comercial or "", arr_keys)
        if a is None or a.id in matched_ids:
            continue
        matched_ids.add(a.id)
        if p.id in proy_con_contrato_arr:
            con_contrato += 1
        else:
            sin_contrato.append(f"{a.nombre} → {p.nombre_comercial}")

    sin_match = [a.nombre for a in arr if a.id not in matched_ids]

    return {
        "total_arr_proyectos":     len(arr),
        "con_contrato_arriendo":   con_contrato,
        "sin_contrato_arriendo":   len(sin_contrato),
        "sin_match_de_proyecto":   len(sin_match),
        "ejemplos_sin_contrato":   sin_contrato[:30],
        "ejemplos_sin_match":      sin_match[:30],
    }


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
            sel.motivo_exclusion = item.motivo_exclusion
        else:
            sel = ArrSeleccion(arr_proyecto_id=item.proyecto_id, periodo=periodo,
                               incluido=item.incluido, facturado=False,
                               motivo_exclusion=item.motivo_exclusion)
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
        nuevo_estado = True
    else:
        sel.facturado = not sel.facturado
        nuevo_estado = sel.facturado
        # Al desmarcar, se descongela: si no, un canon congelado por error queda pegado.
        if not nuevo_estado:
            sel.valor_facturado_congelado = None

    # Al marcar como facturado, congelar el canon calculado en ese momento.
    if nuevo_estado and sel.valor_facturado_congelado is None:
        p = db.query(ArrProyecto).filter(ArrProyecto.id == proyecto_id).first()
        if p is not None:
            ipc = {r.año: float(r.tasa) for r in db.query(ArrIPCTasa).all()}
            fila = calcular_arriendo(
                proyecto_id=p.id, nombre=p.nombre, codigo=p.codigo,
                fecha_firma_contrato=p.fecha_firma_contrato,
                valor_base=float(p.valor_base) if p.valor_base is not None else None,
                canon_archivo=float(p.canon_archivo) if p.canon_archivo is not None else None,
                periodo=periodo, ipc_tasas=ipc,
            )
            sel.valor_facturado_congelado = fila["canon_a_facturar"]

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

    directorio = _UPLOADS_DIR / periodo / _safe_segment(codigo_contrato)
    directorio.mkdir(parents=True, exist_ok=True)

    # Guardar archivo principal
    ext_principal = _Path(file.filename or "doc.pdf").suffix or ".pdf"
    nombre_archivo = nombre_resultante if nombre_resultante.endswith(ext_principal) else nombre_resultante + ext_principal
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

    directorio = _UPLOADS_DIR / periodo / _safe_segment(codigo_contrato)
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
