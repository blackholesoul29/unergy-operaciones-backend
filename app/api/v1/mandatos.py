"""API de la pestaña Mandatos (Costos).

Endpoints:
  GET    /mandatos?periodo=2025-05          → lista del período
  GET    /mandatos/resumen?periodo=2025-05  → conteos de métricas
  GET    /mandatos/periodos                 → períodos existentes + badges
  POST   /mandatos                          → crear manual
  PATCH  /mandatos/{id}                     → editar / cambiar estado / asignar inversionista
  POST   /mandatos/upload-firmado           → subir PDF firmado (asocia por CMU del nombre)
  POST   /mandatos/{id}/asociar-pdf         → asociar PDF subido a un CMU manualmente
  DELETE /mandatos/{id}                     → eliminar
  POST   /mandatos/ejecutar-ingesta         → correr la lectura de correo AHORA (admin)
  GET    /mandatos/diagnostico-imap          → probar la conexión IMAP (solo lee)
  GET    /mandatos/correos                  → bitácora de correos leídos por IMAP
  POST   /mandatos/correos/{id}/revertir    → revertir cambios de un correo
  GET    /mandato-inversionistas            → tabla maestra
"""
from __future__ import annotations
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.auth import _require_admin, get_current_user
from app.core.database import get_db
from app.models.mandatos import Mandato, MandatoInversionista, EstadoMandatoCostoEnum, MandatoCorreo
from app.schemas.mandatos import MandatoCrear, MandatoActualizar, InversionistaOut
from app.services.mandatos_service import (
    mandato_to_dict, calcular_resumen, transicion_valida, extraer_cmu_de_nombre,
    parsear_nombre_zip, match_inversionista,
)

router = APIRouter(prefix="/mandatos", tags=["Mandatos"])
maestra_router = APIRouter(prefix="/mandato-inversionistas", tags=["Mandatos"])

_PDF_DIR = Path("uploads/mandatos")
_PDF_DIR.mkdir(parents=True, exist_ok=True)

_ZIP_DIR = Path("uploads/mandatos/zips")
_ZIP_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/ejecutar-ingesta")
def ejecutar_ingesta(_=Depends(_require_admin)):
    """Corre la lectura de correo AHORA, sin esperar al cron de las :05.

    **Esto escribe.** Hace exactamente lo mismo que el cron: lee el buzón,
    aplica lo que encuentra a finanzas_mandatos y registra todo en la bitácora.

    Existe porque el cron solo corre de 7am a 7pm; sin esto, una primera tanda
    que caiga fuera de esa ventana se procesaría de madrugada sin nadie
    mirando. Correrlo cuando alguien está pendiente es más seguro.

    Es POST y no GET a propósito: un GET se dispara con solo abrir la URL, y
    con un prefetch del navegador podría ejecutarse sin que nadie lo pidiera.
    Pide rol admin por la misma razón -- no es una consulta, es una acción.

    Volver a correrlo es inofensivo: la deduplicación va por Message-ID, así
    que los correos ya procesados se saltan.
    """
    from app.services.mandatos.finanzas_sync import revisar_correos_finanzas

    return revisar_correos_finanzas()


@router.get("/diagnostico-imap")
def diagnostico_imap_endpoint(_=Depends(get_current_user)):
    """Prueba la conexión IMAP a demanda y devuelve lo que encontraría.

    Existe porque el cron corre a los :05 y esperar una hora para saber si el
    App Password sirve es absurdo. Solo lee: no toca la base de datos ni
    modifica el buzón. Provisional, igual que el módulo que invoca -- se borra
    junto con él cuando la ingesta real entre en servicio.
    """
    from app.services.mandatos.diagnostico import diagnostico_imap

    return diagnostico_imap()


@router.get("/correos")
def listar_correos(limite: int = 100, solo_revision: bool = False,
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Bitácora de correos leídos por IMAP, del más reciente al más viejo."""
    q = select(MandatoCorreo).order_by(MandatoCorreo.fecha.desc())
    if solo_revision:
        q = q.where(MandatoCorreo.requiere_revision.is_(True))
    filas = db.execute(q.limit(min(limite, 500))).scalars().all()
    return [{
        "id": f.id, "fecha": f.fecha.isoformat(), "remitente": f.remitente,
        "asunto": f.asunto, "fuente": f.fuente, "clasificacion": f.clasificacion,
        "resultado": f.resultado, "requiere_revision": f.requiere_revision,
        "revertido": f.revertido, "detalle": f.detalle,
    } for f in filas]


@router.post("/correos/{correo_id}/revertir")
def revertir_correo(correo_id: int, db: Session = Depends(get_db),
                    _=Depends(get_current_user)):
    """Devuelve a su valor previo todos los campos que este correo cambió en
    cada mandato: estado, observación, fechas y referencias de correo.

    No borra PDFs guardados ni la fila de bitácora, y tampoco desasocia
    pdf_firmado_ruta/pdf_firmado_nombre: revertir un estado no des-firma un
    documento que sí existe, así que esos dos campos se dejan intactos a
    propósito aunque el correo los haya asignado.
    """
    fila = db.get(MandatoCorreo, correo_id)
    if not fila:
        raise HTTPException(404, "Correo no encontrado.")
    if fila.revertido:
        raise HTTPException(409, "Este correo ya fue revertido.")

    revertidos = []
    for accion in (fila.detalle or {}).get("acciones", []):
        if accion.get("resultado") != "aplicado":
            continue
        m = db.get(Mandato, accion.get("mandato_id"))
        if not m:
            continue
        m.estado = accion["estado_previo"]
        if "observacion_previa" in accion:
            m.observacion = accion["observacion_previa"]
        if "fecha_firmado_previa" in accion:
            m.fecha_firmado = accion["fecha_firmado_previa"]
        if "fecha_envio_inversionista_previa" in accion:
            valor = accion["fecha_envio_inversionista_previa"]
            m.fecha_envio_inversionista = date.fromisoformat(valor) if valor else None
        if "correo_ref_envio_previo" in accion:
            m.correo_ref_envio = accion["correo_ref_envio_previo"]
        if "correo_ref_revisoria_previo" in accion:
            m.correo_ref_revisoria = accion["correo_ref_revisoria_previo"]
        revertidos.append(m.cmu)

    fila.revertido = True
    fila.requiere_revision = True
    db.commit()
    return {"revertidos": revertidos, "total": len(revertidos)}


def _periodo_a_date(periodo: str) -> date:
    """'2025-05' → date(2025,5,1)."""
    try:
        anio, mes = periodo.split("-")
        return date(int(anio), int(mes), 1)
    except Exception:
        raise HTTPException(400, "Parámetro 'periodo' inválido, formato esperado YYYY-MM.")


@router.get("")
def listar(periodo: str = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = _periodo_a_date(periodo)
    filas = db.execute(
        select(Mandato).where(Mandato.periodo == p).order_by(Mandato.cmu)
    ).scalars().all()
    return [mandato_to_dict(f) for f in filas]


@router.get("/resumen")
def resumen(periodo: str = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = _periodo_a_date(periodo)
    filas = db.execute(select(Mandato).where(Mandato.periodo == p)).scalars().all()
    return calcular_resumen(filas)


@router.get("/periodos")
def periodos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Lista de períodos con datos + badge (ámbar si hay correcciones sin resolver)."""
    filas = db.execute(select(Mandato.periodo, Mandato.estado)).all()
    por_periodo: dict[str, list[str]] = {}
    for periodo_val, estado in filas:
        clave = periodo_val.strftime("%Y-%m")
        por_periodo.setdefault(clave, []).append(estado)
    out = []
    for clave in sorted(por_periodo.keys(), reverse=True):
        estados = por_periodo[clave]
        tiene_correcciones = any(e == "con_correcciones" for e in estados)
        cerrado = all(e == "enviado_inversionista" for e in estados)
        out.append({
            "periodo": clave,
            "badge": "correcciones" if tiene_correcciones else ("cerrado" if cerrado else "abierto"),
        })
    return out


@router.post("", status_code=201)
def crear(payload: MandatoCrear, db: Session = Depends(get_db), _=Depends(get_current_user)):
    existe = db.execute(
        select(Mandato).where(Mandato.cmu == payload.cmu, Mandato.periodo == payload.periodo)
    ).scalar_one_or_none()
    if existe:
        raise HTTPException(409, f"Ya existe el mandato {payload.cmu} en ese período.")
    m = Mandato(**payload.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return mandato_to_dict(m)


@router.patch("/{mandato_id}")
def actualizar(mandato_id: int, payload: MandatoActualizar,
               db: Session = Depends(get_db), _=Depends(get_current_user)):
    m = db.get(Mandato, mandato_id)
    if not m:
        raise HTTPException(404, "Mandato no encontrado.")
    datos = payload.model_dump(exclude_unset=True)
    nuevo_estado = datos.get("estado")
    if nuevo_estado and nuevo_estado != m.estado and not transicion_valida(m.estado, nuevo_estado):
        raise HTTPException(422, f"Transición de estado inválida: {m.estado} → {nuevo_estado}.")
    for campo, valor in datos.items():
        setattr(m, campo, valor)
    db.commit()
    db.refresh(m)
    return mandato_to_dict(m)


@router.post("/upload-firmado")
async def upload_firmado(periodo: str = Form(...), file: UploadFile = File(...),
                         db: Session = Depends(get_db), _=Depends(get_current_user)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "El archivo debe ser un PDF.")
    contenido = await file.read()
    if len(contenido) > 20 * 1024 * 1024:
        raise HTTPException(413, "Archivo demasiado grande (máx. 20 MB).")

    destino = _PDF_DIR / file.filename
    destino.write_bytes(contenido)
    ruta = str(destino)

    cmu = extraer_cmu_de_nombre(file.filename)
    if not cmu:
        return {"asociado": False, "ruta": ruta, "nombre": file.filename,
                "mensaje": "No se pudo identificar el CMU del nombre. Asocia el PDF manualmente."}

    p = _periodo_a_date(periodo)
    m = db.execute(
        select(Mandato).where(Mandato.cmu == cmu, Mandato.periodo == p)
    ).scalar_one_or_none()
    if not m:
        return {"asociado": False, "ruta": ruta, "nombre": file.filename, "cmu": cmu,
                "mensaje": f"No existe el mandato {cmu} en {periodo}. Asócialo manualmente."}

    m.pdf_firmado_ruta = ruta
    m.pdf_firmado_nombre = file.filename
    m.fecha_firmado = m.fecha_firmado or date.today()
    if transicion_valida(m.estado, "firmado"):
        m.estado = "firmado"
    db.commit()
    db.refresh(m)
    return {"asociado": True, "mandato": mandato_to_dict(m)}


@router.post("/{mandato_id}/asociar-pdf")
def asociar_pdf(mandato_id: int, nombre: str = Form(...),
                db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Asocia manualmente un PDF ya subido a `_PDF_DIR` (vía upload-firmado) a
    otro mandato. Solo recibe el nombre de archivo (no una ruta) para no permitir
    que el cliente apunte a un archivo arbitrario del servidor."""
    m = db.get(Mandato, mandato_id)
    if not m:
        raise HTTPException(404, "Mandato no encontrado.")
    destino = _PDF_DIR / Path(nombre).name
    try:
        destino.resolve().relative_to(_PDF_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Nombre de archivo inválido.")
    if not destino.is_file():
        raise HTTPException(404, "El archivo no existe en el servidor. Súbelo primero con 'Subir firmados'.")
    m.pdf_firmado_ruta = str(destino)
    m.pdf_firmado_nombre = destino.name
    m.fecha_firmado = m.fecha_firmado or date.today()
    if transicion_valida(m.estado, "firmado"):
        m.estado = "firmado"
    db.commit()
    db.refresh(m)
    return mandato_to_dict(m)


@router.delete("/{mandato_id}", status_code=204)
def eliminar(mandato_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    m = db.get(Mandato, mandato_id)
    if not m:
        raise HTTPException(404, "Mandato no encontrado.")
    db.delete(m)
    db.commit()


@router.post("/upload-zip")
async def upload_zip(periodo: str = Form(...), file: UploadFile = File(...),
                     db: Session = Depends(get_db), _=Depends(get_current_user)):
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "El archivo debe ser un .zip")
    contenido = await file.read()
    if len(contenido) > 100 * 1024 * 1024:
        raise HTTPException(413, "Archivo demasiado grande (máx. 100 MB).")
    p = _periodo_a_date(periodo)

    try:
        zf = zipfile.ZipFile(io.BytesIO(contenido))
        nombres = [n for n in zf.namelist() if n.lower().endswith(".pdf") and not n.endswith("/")]
    except zipfile.BadZipFile:
        raise HTTPException(422, "El archivo no es un ZIP válido.")

    maestra = [{"id": i.id, "nombre": i.nombre}
               for i in db.execute(select(MandatoInversionista)).scalars().all()]

    detectados = creados = omitidos = identificados_auto = sin_inversionista = 0
    no_parseables: list[str] = []
    sugerencias: list[dict] = []

    for nombre in nombres:
        base = nombre.split("/")[-1]
        parsed = parsear_nombre_zip(base)
        if not parsed:
            no_parseables.append(base)
            continue
        detectados += 1
        existe = db.execute(
            select(Mandato).where(Mandato.cmu == parsed["cmu"], Mandato.periodo == p)
        ).scalar_one_or_none()
        if existe:
            omitidos += 1
            continue
        inv_id, sugerencia, _score = match_inversionista(parsed["inversionista"], maestra)
        estado = "pendiente_envio" if inv_id else "sin_inversionista"
        m = Mandato(cmu=parsed["cmu"], periodo=p, proyecto=parsed["proyecto"],
                    tercero=parsed["inversionista"], inversionista_id=inv_id,
                    estado=estado, archivo_zip_nombre=base)
        db.add(m)
        db.flush()
        creados += 1
        if inv_id:
            identificados_auto += 1
        else:
            sin_inversionista += 1
            if sugerencia:
                sugerencias.append({"mandato_id": m.id, "cmu": parsed["cmu"],
                                    "nombre_extraido": parsed["inversionista"], **sugerencia})

    (_ZIP_DIR / f"{periodo}.zip").write_bytes(contenido)
    db.commit()
    return {
        "detectados": detectados, "creados": creados, "omitidos": omitidos,
        "identificados_auto": identificados_auto, "sin_inversionista": sin_inversionista,
        "no_parseables": no_parseables, "sugerencias": sugerencias,
    }


@router.get("/{mandato_id}/pdf")
def descargar_pdf(mandato_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Sirve el PDF firmado del mandato, sin importar si llegó por 'Subir
    firmados' (archivo suelto en _PDF_DIR) o dentro del ZIP del período."""
    m = db.get(Mandato, mandato_id)
    if not m:
        raise HTTPException(404, "Mandato no encontrado.")

    if m.pdf_firmado_ruta:
        ruta = Path(m.pdf_firmado_ruta)
        try:
            ruta.resolve().relative_to(_PDF_DIR.resolve())
        except ValueError:
            raise HTTPException(404, "PDF no disponible.")
        if not ruta.is_file():
            raise HTTPException(404, "El archivo del PDF ya no existe en el servidor.")
        return StreamingResponse(
            io.BytesIO(ruta.read_bytes()), media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{m.pdf_firmado_nombre or ruta.name}"'},
        )

    if m.archivo_zip_nombre:
        periodo = m.periodo.strftime("%Y-%m")
        zpath = _ZIP_DIR / f"{periodo}.zip"
        if not zpath.exists():
            raise HTTPException(404, "No se encontró el ZIP del período.")
        zf = zipfile.ZipFile(zpath)
        entry = next((n for n in zf.namelist() if n.split("/")[-1] == m.archivo_zip_nombre), None)
        if not entry:
            raise HTTPException(404, "El PDF no está dentro del ZIP del período.")
        data = zf.read(entry)
        return StreamingResponse(
            io.BytesIO(data), media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{m.archivo_zip_nombre}"'},
        )

    raise HTTPException(404, "Este mandato no tiene PDF asociado.")


@maestra_router.get("")
def listar_maestra(db: Session = Depends(get_db), _=Depends(get_current_user)):
    filas = db.execute(
        select(MandatoInversionista).order_by(MandatoInversionista.nombre)
    ).scalars().all()
    return [InversionistaOut.model_validate(f).model_dump() for f in filas]
