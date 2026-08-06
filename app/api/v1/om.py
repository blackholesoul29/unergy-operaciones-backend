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
  PATCH /om/factura/{periodo}/sin-match/{id}/asignar  → asigna manualmente una página sin match a un contrato
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.contratos import ContratoServicio
from app.models.proyectos import Proyecto
from app.models.om import IPCTasa, OMSeleccion, OMFacturaMensual, OMDocumentoProyecto, OMPaginaSinMatch
from app.schemas.om import (
    IPCTasaOut, IPCTasaUpsert,
    OMContratoOut, OMCalculoFila, OMCalculoResponse,
    OMSeleccionGuardar, OMSeleccionOut,
    OMSinMatchAsignar,
    OMIndexacionFila, OMIndexacionResponse,
)
from app.services.om_calculator import calcular_proyecto, serie_indexacion
from datetime import date
from app.utils.periodo import periodo_valido, anio_valido, ANIO_MIN, ANIO_MAX


def _check_periodo(periodo: str) -> None:
    if not periodo_valido(periodo):
        raise HTTPException(400, "periodo debe tener formato YYYY-MM (mes 01-12)")
from app.services.om_pdf_splitter import dividir_pdf, extraer_pagina_datos, escribir_o_anexar_pagina, safe_filename

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
        .join(Proyecto, ContratoServicio.proyecto_id == Proyecto.id)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento",
                Proyecto.estado == "en_operacion")
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
    _check_periodo(periodo)

    tasas_rows = db.query(IPCTasa).all()
    ipc_tasas = {r.año: float(r.tasa) for r in tasas_rows}

    selecciones = {
        s.contrato_id: s
        for s in db.query(OMSeleccion).filter(OMSeleccion.periodo == periodo).all()
    }

    # Documentos por proyecto para este período: contrato_id → nombre_archivo.
    # Solo se marca disponible si el archivo EXISTE físicamente: el registro en BD
    # puede quedar apuntando a un archivo perdido (p.ej. subido antes del volumen
    # persistente), y en ese caso el ícono de descarga no debe aparecer.
    documentos_nombre = {}
    for d in (db.query(OMDocumentoProyecto)
                .filter(OMDocumentoProyecto.periodo == periodo).all()):
        if d.ruta_local and _Path(d.ruta_local).exists():
            documentos_nombre[d.contrato_id] = d.nombre_archivo

    # Todos los proyectos EN OPERACIÓN con el servicio de Operación contratado
    # (Proyecto.srv_operacion) — tengan o no contrato de mantenimiento.
    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.estado == "en_operacion", Proyecto.srv_operacion == True)  # noqa: E712
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    # Contrato de mantenimiento por proyecto (el primero si hubiera varios).
    contrato_por_proyecto: dict[int, ContratoServicio] = {}
    for c in (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento",
                ContratoServicio.proyecto_id.isnot(None))
        .order_by(ContratoServicio.id)
        .all()
    ):
        contrato_por_proyecto.setdefault(c.proyecto_id, c)

    filas = []
    total = 0

    for p in proyectos:
        c = contrato_por_proyecto.get(p.id)

        if c is None:
            # En operación pero SIN contrato de mantenimiento → solo visible, no facturable.
            fila_data = calcular_proyecto(
                contrato_id=-p.id,   # id sintético (negativo) para la key del front; no se persiste
                nombre_proyecto=p.nombre_comercial or f"Proyecto #{p.id}",
                codigo_tsf=p.codigo_tsf,
                fecha_firma_contrato=None, fecha_inicio_om=None, valor_base_anual=None,
                periodo=periodo, ipc_tasas=ipc_tasas,
            )
            fila_data["estado_contrato"] = "sin_contrato"
            fila_data["aplica_este_mes"] = False
            fila_data["tipo_proyecto"]   = p.tipo_proyecto
            filas.append(OMCalculoFila(**fila_data))
            continue

        estado_contrato = "con_contrato" if c.estado == "vigente" else "en_tramite"
        sel = selecciones.get(c.id)
        incluido = sel.incluido if sel else True
        facturado = sel.facturado if sel else False
        valor_manual = float(sel.valor_manual) if sel and sel.valor_manual is not None else None

        fila_data = calcular_proyecto(
            contrato_id=c.id,
            nombre_proyecto=p.nombre_comercial or c.prestador_nombre or f"Contrato #{c.id}",
            codigo_tsf=p.codigo_tsf,
            fecha_firma_contrato=c.fecha_firma_contrato,
            # Fecha base de indexación = inicio O&M: la columna dedicada o, si falta,
            # la "Fecha de inicio O&M" que edita el diálogo (c.fecha_inicio).
            fecha_inicio_om=c.fecha_inicio_om or c.fecha_inicio,
            valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
            periodo=periodo,
            ipc_tasas=ipc_tasas,
            incluido=incluido,
            facturado=facturado,
            valor_manual=valor_manual,
            valor_congelado=(int(sel.valor_facturado_congelado)
                             if sel and sel.valor_facturado_congelado is not None else None),
            periodicidad=c.periodicidad_pago,
        )
        fila_data["estado_contrato"]      = estado_contrato
        fila_data["tipo_proyecto"]        = p.tipo_proyecto
        fila_data["motivo_exclusion"]     = sel.motivo_exclusion if sel else None
        fila_data["documento_disponible"] = c.id in documentos_nombre
        fila_data["documento_nombre"]     = documentos_nombre.get(c.id)
        fila = OMCalculoFila(**fila_data)
        filas.append(fila)

        # Solo se factura si el contrato está vigente ("con contrato").
        if estado_contrato == "con_contrato" and fila.incluido and fila.habilitado and fila.valor_a_facturar:
            total += fila.valor_a_facturar

    return OMCalculoResponse(periodo=periodo, filas=filas, total_seleccionado=total)


@router.get("/indexacion/{contrato_id}", response_model=OMIndexacionResponse)
def indexacion_contrato(
    contrato_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Serie de indexación (anual y mensual) de un contrato de mantenimiento,
    calculada automáticamente con el mismo motor que el panel de Costos —
    aniversario desde la Fecha de inicio O&M + IPC por año, solo aniversarios
    cumplidos a hoy."""
    c = db.get(ContratoServicio, contrato_id)
    if c is None or c.servicio_aplica != "mantenimiento":
        raise HTTPException(404, "Contrato de mantenimiento no encontrado")

    ipc_tasas = {r.año: float(r.tasa) for r in db.query(IPCTasa).all()}
    fecha_base = c.fecha_inicio_om or c.fecha_inicio
    valor_base = float(c.tarifa_base) if c.tarifa_base else None

    hoy = date.today()
    serie = serie_indexacion(fecha_base, valor_base, ipc_tasas, hoy.year, hoy.month)

    anual = [OMIndexacionFila(anio=f["anio"], ipc_aplicado=f["ipc_aplicado"], valor=f["valor_anual"])
             for f in serie]
    mensual = [OMIndexacionFila(anio=f["anio"], ipc_aplicado=f["ipc_aplicado"], valor=f["valor_mensual"])
               for f in serie]
    return OMIndexacionResponse(anual=anual, mensual=mensual)


# ── Selección mensual ────────────────────────────────────────────────────────

@router.get("/seleccion/{periodo}", response_model=list[OMSeleccionOut])
def obtener_seleccion(
    periodo: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    _check_periodo(periodo)
    return db.query(OMSeleccion).filter(OMSeleccion.periodo == periodo).all()


@router.post("/seleccion/{periodo}", response_model=list[OMSeleccionOut])
def guardar_seleccion(
    periodo: str,
    payload: OMSeleccionGuardar,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Guarda / actualiza la selección de contratos para el período (upsert)."""
    _check_periodo(periodo)
    resultados = []
    for item in payload.items:
        sel = db.query(OMSeleccion).filter(
            OMSeleccion.contrato_id == item.contrato_id,
            OMSeleccion.periodo == periodo,
        ).first()

        if sel:
            sel.incluido = item.incluido
            sel.valor_manual = item.valor_manual
            sel.motivo_exclusion = item.motivo_exclusion
        else:
            sel = OMSeleccion(
                contrato_id=item.contrato_id,
                periodo=periodo,
                incluido=item.incluido,
                facturado=False,
                valor_manual=item.valor_manual,
                motivo_exclusion=item.motivo_exclusion,
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
    _check_periodo(periodo)
    sel = db.query(OMSeleccion).filter(
        OMSeleccion.contrato_id == contrato_id,
        OMSeleccion.periodo == periodo,
    ).first()

    if not sel:
        sel = OMSeleccion(contrato_id=contrato_id, periodo=periodo, incluido=True, facturado=True)
        db.add(sel)
        nuevo_estado = True
    else:
        sel.facturado = not sel.facturado
        nuevo_estado = sel.facturado
        # Al desmarcar, se descongela: si no, un valor congelado por error (p.ej.
        # capturado antes de un arreglo de indexación) quedaría pegado para siempre.
        if not nuevo_estado:
            sel.valor_facturado_congelado = None

    # #4: al pasar a facturado, congelar el valor calculado en ese momento.
    if nuevo_estado and sel.valor_facturado_congelado is None:
        c = db.get(ContratoServicio, contrato_id)
        if c is not None:
            ipc = {r.año: float(r.tasa) for r in db.query(IPCTasa).all()}
            nombre = (c.proyecto.nombre_comercial if c.proyecto
                      else c.prestador_nombre or f"Contrato #{c.id}")
            fila = calcular_proyecto(
                contrato_id=c.id, nombre_proyecto=nombre,
                fecha_firma_contrato=c.fecha_firma_contrato,
                fecha_inicio_om=c.fecha_inicio_om or c.fecha_inicio,
                valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
                periodo=periodo, ipc_tasas=ipc,
                valor_manual=float(sel.valor_manual) if sel.valor_manual is not None else None,
            )
            sel.valor_facturado_congelado = fila["valor_a_facturar"]

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
    if not anio_valido(año):
        raise HTTPException(400, f"año fuera de rango permitido ({ANIO_MIN}-{ANIO_MAX})")
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
                "tiene_archivo": False, "subido_en": None, "sin_match_pendientes": []}
    tiene_archivo = bool(
        factura.ruta_local and _Path(factura.ruta_local).exists()
    )
    sin_match_pendientes = (
        db.query(OMPaginaSinMatch)
        .filter(OMPaginaSinMatch.periodo == periodo, OMPaginaSinMatch.resuelto == False)  # noqa: E712
        .order_by(OMPaginaSinMatch.pagina)
        .all()
    )
    return {
        "periodo":        periodo,
        "nombre_archivo": factura.nombre_archivo,
        "enlace_pdf":     factura.enlace_pdf,
        "tiene_archivo":  tiene_archivo,
        "subido_en":      factura.subido_en,
        "sin_match_pendientes": [
            {
                "id": s.id, "pagina": s.pagina, "nombre_extraido": s.nombre_extraido,
                "razon": s.razon, "numero_factura": s.numero_factura, "origen": s.origen,
            }
            for s in sin_match_pendientes
        ],
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
    # El splitter empareja páginas contra TODOS los contratos de mantenimiento
    # (no se filtra por estado del proyecto: una factura puede incluir proyectos
    # en cualquier estado; el filtro por 'en_operacion' es solo para el panel).
    contratos = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento")
        .order_by(ContratoServicio.id)
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

    # #9: eliminar documentos huérfanos — contratos que tenían documento en este
    # período pero que ya NO aparecen en el split nuevo. Solo si el split procesó
    # algo (si procesó 0, no se borra nada para no perder datos por una subida mala).
    contratos_nuevos = {item["contrato_id"] for item in splitting_result["procesados"]}
    if contratos_nuevos:
        db.query(OMDocumentoProyecto).filter(
            OMDocumentoProyecto.periodo == periodo,
            OMDocumentoProyecto.contrato_id.notin_(contratos_nuevos),
        ).delete(synchronize_session=False)

    # Una resubida invalida la numeración de página de los sin_match anteriores
    # de este período — se reemplazan por los que salen del split actual.
    db.query(OMPaginaSinMatch).filter(OMPaginaSinMatch.periodo == periodo).delete()
    for item in splitting_result["sin_match"]:
        db.add(OMPaginaSinMatch(
            periodo=periodo,
            pagina=item["pagina"],
            nombre_extraido=item.get("nombre_extraido"),
            estrategia=item.get("estrategia"),
            razon=item["razon"],
            numero_factura=item.get("numero_factura"),
            muestra_texto=item.get("muestra_texto"),
            origen="upload",
        ))

    db.commit()  # commit único para factura + documentos + sin_match

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


@router.patch("/factura/{periodo}/sin-match/{sin_match_id}/asignar")
def asignar_sin_match(
    periodo: str,
    sin_match_id: int,
    payload: OMSinMatchAsignar,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """
    Asigna manualmente una página que no se pudo emparejar automáticamente
    (`OMPaginaSinMatch`) a un contrato de mantenimiento: extrae esa página del
    PDF consolidado original y la anexa al documento individual del contrato
    para ese período (creándolo si no existía).
    """
    sin_match = db.query(OMPaginaSinMatch).filter(
        OMPaginaSinMatch.id == sin_match_id,
        OMPaginaSinMatch.periodo == periodo,
    ).first()
    if not sin_match:
        raise HTTPException(404, "No existe esa página sin match para este período")
    if sin_match.resuelto:
        raise HTTPException(400, "Esta página ya fue asignada")

    factura = db.query(OMFacturaMensual).filter(OMFacturaMensual.periodo == periodo).first()
    if not factura or not factura.ruta_local or not _Path(factura.ruta_local).exists():
        raise HTTPException(404, "No hay PDF consolidado original disponible para este período")

    contrato = db.query(ContratoServicio).filter(
        ContratoServicio.id == payload.contrato_id,
        ContratoServicio.servicio_aplica == "mantenimiento",
    ).first()
    if not contrato:
        raise HTTPException(404, "El contrato indicado no es un contrato de mantenimiento válido")

    nombre_proyecto = (
        contrato.proyecto.nombre_comercial if contrato.proyecto
        else contrato.prestador_nombre or f"Contrato #{contrato.id}"
    )

    ruta_pdf_origen = _Path(factura.ruta_local)
    datos = extraer_pagina_datos(ruta_pdf_origen, sin_match.pagina)

    directorio_docs = _UPLOADS_DIR / "documentos" / periodo
    nombre_archivo = f"SOFV_{safe_filename(nombre_proyecto)}_{periodo}_mantenimiento.pdf"
    ruta_salida = directorio_docs / nombre_archivo
    escribir_o_anexar_pagina(ruta_pdf_origen, sin_match.pagina, ruta_salida)

    doc = db.query(OMDocumentoProyecto).filter(
        OMDocumentoProyecto.contrato_id == contrato.id,
        OMDocumentoProyecto.periodo == periodo,
    ).first()
    if doc:
        doc.nombre_archivo      = nombre_archivo
        doc.ruta_local          = str(ruta_salida)
        doc.numero_factura      = datos.get("numero_factura") or doc.numero_factura
        doc.total_sin_impuestos = datos.get("total_sin_impuestos") or doc.total_sin_impuestos
        doc.iva                 = datos.get("iva") or doc.iva
        doc.total_pagar         = datos.get("total_pagar") or doc.total_pagar
        doc.fecha_facturacion   = datos.get("fecha_facturacion") or doc.fecha_facturacion
        doc.cufe                = datos.get("cufe") or doc.cufe
    else:
        doc = OMDocumentoProyecto(
            contrato_id=contrato.id,
            periodo=periodo,
            nombre_archivo=nombre_archivo,
            ruta_local=str(ruta_salida),
            numero_factura=datos.get("numero_factura"),
            total_sin_impuestos=datos.get("total_sin_impuestos"),
            iva=datos.get("iva"),
            total_pagar=datos.get("total_pagar"),
            fecha_facturacion=datos.get("fecha_facturacion"),
            cufe=datos.get("cufe"),
        )
        db.add(doc)

    sin_match.resuelto             = True
    sin_match.contrato_id_asignado = contrato.id
    sin_match.asignado_en          = func.now()

    db.commit()
    db.refresh(doc)
    return {
        "ok": True,
        "contrato_id": contrato.id,
        "nombre_proyecto": nombre_proyecto,
        "documento_nombre": doc.nombre_archivo,
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
