"""Orquestación: correos → decisiones → base de datos.

Separado en dos mitades a propósito:
  - decidir_acciones(): pura. Correo → qué habría que hacer. Testeable sola.
  - aplicar_correo(): impura. Toma esas decisiones y las escribe en la BD,
    respetando la máquina de estados y sin pisar cambios manuales.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.mandatos import Mandato, MandatoCorreo
from app.services.mandatos.email_parser import (
    CLASIF_MOLDE_SIMPLE, CLASIF_SEGUIMIENTO, clasificar_correo,
    cmu_al_inicio_de_nombre, extraer_observaciones, solo_pdfs,
)
from app.services.mandatos.imap_client import CorreoCrudo, buscar_correos
from app.services.mandatos_service import extraer_cmu_de_nombre, transicion_valida

logger = logging.getLogger("mandatos.email_sync")

FUENTE_REVISORIA = "revisoria"
FUENTE_ENVIO = "envio_inversionista"

REMITENTE_REVISORIA = "vlondono@jbp.com.co"
REMITENTE_ENVIO = "jessica@unergy.io"

_PDF_DIR = Path("uploads/mandatos")


def decidir_acciones(correo: CorreoCrudo, fuente: str) -> dict:
    """Correo → {'clasificacion', 'acciones', 'requiere_revision', 'adjuntos_sin_cmu'}.

    Cada acción es {'cmu', 'estado_destino', 'observacion', 'adjunto'}. Pura: no
    consulta la base ni escribe archivos, solo dice qué habría que hacer.
    """
    nombres = [n for n, _ in correo.adjuntos]
    pdfs = solo_pdfs(nombres)
    acciones: list[dict] = []
    adjuntos_sin_cmu: list[str] = []

    if fuente == FUENTE_ENVIO:
        # Fuente 3: el CMU viene en el nombre del adjunto. El cuerpo no se lee --
        # por eso los correos de "Liquidación preliminar", que mencionan
        # "certificados de mandato" sin adjuntarlos, no producen nada.
        for nombre in pdfs:
            cmu = cmu_al_inicio_de_nombre(nombre)
            if cmu:
                acciones.append({"cmu": cmu, "estado_destino": "enviado_inversionista",
                                 "observacion": None, "adjunto": nombre})
        return {"clasificacion": CLASIF_MOLDE_SIMPLE if acciones else "desconocido",
                "acciones": acciones, "requiere_revision": False,
                "adjuntos_sin_cmu": []}

    # Fuente 1/2: revisoría.
    clasificacion = clasificar_correo(correo.asunto, correo.cuerpo)

    # Fuente 2 -- los adjuntos se procesan SIEMPRE, cualquiera sea la
    # clasificación: un archivo es un hecho objetivo, no una interpretación.
    cmus_con_pdf: set[str] = set()
    for nombre in pdfs:
        cmu = extraer_cmu_de_nombre(nombre)
        if cmu:
            cmus_con_pdf.add(cmu)
            acciones.append({"cmu": cmu, "estado_destino": "firmado",
                             "observacion": None, "adjunto": nombre})
        else:
            adjuntos_sin_cmu.append(nombre)

    # Fuente 1 -- solo si el texto encaja en el molde conocido.
    if clasificacion == CLASIF_MOLDE_SIMPLE:
        for obs in extraer_observaciones(correo.cuerpo):
            if obs["cmu"] in cmus_con_pdf:
                continue        # el PDF firmado manda sobre la observación
            acciones.append({"cmu": obs["cmu"], "estado_destino": "con_correcciones",
                             "observacion": obs["observacion"], "adjunto": None})

    requiere_revision = clasificacion != CLASIF_MOLDE_SIMPLE or bool(adjuntos_sin_cmu)
    return {"clasificacion": clasificacion, "acciones": acciones,
            "requiere_revision": requiere_revision,
            "adjuntos_sin_cmu": adjuntos_sin_cmu}


def _guardar_adjunto(nombre: str, contenido: bytes) -> str:
    _PDF_DIR.mkdir(parents=True, exist_ok=True)
    destino = _PDF_DIR / nombre
    destino.write_bytes(contenido)
    return str(destino)


def _aplicar_accion(db: Session, accion: dict, correo: CorreoCrudo, fuente: str) -> dict:
    """Aplica una acción a su mandato. Devuelve el registro para `detalle`.

    Nunca fuerza una transición: si la máquina de estados no la permite, se
    registra el conflicto y el mandato queda como estaba.
    """
    cmu = accion["cmu"]
    # El correo no dice a qué período pertenece el CMU. La restricción única es
    # (cmu, periodo), así que en teoría un mismo CMU puede repetirse entre
    # períodos; se toma el más reciente, que es el que está en curso.
    m = db.execute(
        select(Mandato).where(Mandato.cmu == cmu).order_by(Mandato.periodo.desc())
    ).scalars().first()
    if not m:
        return {"cmu": cmu, "resultado": "cmu_no_encontrado"}

    destino = accion["estado_destino"]
    estado_previo = m.estado
    fecha_correo = correo.fecha.date()

    # Un PDF de envío a inversionista es evidencia de que el mandato fue firmado.
    # Si viene desde enviado_revisoria o corregido, se encadena firmado →
    # enviado_inversionista. Desde con_correcciones NO: enviar al inversionista
    # un mandato con observaciones pendientes es una anomalía que debe verse.
    cadena = [destino]
    if destino == "enviado_inversionista" and estado_previo in ("enviado_revisoria", "corregido"):
        cadena = ["firmado", "enviado_inversionista"]

    estado = estado_previo
    for paso in cadena:
        if estado == paso:
            continue
        if not transicion_valida(estado, paso):
            return {"cmu": cmu, "resultado": "transicion_invalida",
                    "estado_previo": estado_previo, "estado_destino": paso}
        estado = paso

    if accion["adjunto"]:
        contenido = dict(correo.adjuntos).get(accion["adjunto"])
        if contenido:
            m.pdf_firmado_ruta = _guardar_adjunto(accion["adjunto"], contenido)
            m.pdf_firmado_nombre = accion["adjunto"]

    if estado != estado_previo:
        m.estado = estado
    if accion["observacion"]:
        m.observacion = accion["observacion"]
    if "firmado" in cadena or destino == "firmado":
        m.fecha_firmado = m.fecha_firmado or fecha_correo
    if destino == "enviado_inversionista":
        m.fecha_envio_inversionista = fecha_correo
        m.correo_ref_envio = correo.message_id
    if fuente == FUENTE_REVISORIA:
        m.correo_ref_revisoria = correo.message_id

    return {"cmu": cmu, "resultado": "aplicado", "mandato_id": m.id,
            "estado_previo": estado_previo, "estado_nuevo": estado}


def procesar_correo(db: Session, correo: CorreoCrudo, fuente: str) -> MandatoCorreo:
    """Procesa un correo y devuelve su fila de bitácora (sin commit)."""
    decision = decidir_acciones(correo, fuente)
    registros = [_aplicar_accion(db, a, correo, fuente) for a in decision["acciones"]]
    hubo_cambio = any(r["resultado"] == "aplicado" for r in registros)
    hubo_problema = any(r["resultado"] != "aplicado" for r in registros)

    return MandatoCorreo(
        message_id=correo.message_id,
        fecha=correo.fecha,
        remitente=correo.remitente,
        asunto=correo.asunto[:1000] if correo.asunto else None,
        fuente=fuente,
        clasificacion=decision["clasificacion"],
        resultado="aplicado" if hubo_cambio else "omitido",
        requiere_revision=decision["requiere_revision"] or hubo_problema,
        detalle={"acciones": registros,
                 "adjuntos_sin_cmu": decision["adjuntos_sin_cmu"]},
    )


def revisar_correos_mandatos() -> None:
    """Punto de entrada del cron. Nunca lanza hacia el scheduler.

    Transacción POR CORREO: un correo que revienta no arrastra a los demás.
    """
    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("IMAP mandatos: credenciales no configuradas, se omite la corrida")
        return

    db = SessionLocal()
    try:
        vistos = {mid for (mid,) in db.execute(select(MandatoCorreo.message_id)).all()}
        for remitente, fuente in ((REMITENTE_REVISORIA, FUENTE_REVISORIA),
                                  (REMITENTE_ENVIO, FUENTE_ENVIO)):
            for correo in buscar_correos(remitente):
                if correo.message_id in vistos:
                    continue
                try:
                    fila = procesar_correo(db, correo, fuente)
                    db.add(fila)
                    db.commit()
                    vistos.add(correo.message_id)
                    logger.info("IMAP mandatos: %s -- %s/%s, %d acciones",
                                correo.message_id, fila.clasificacion, fila.resultado,
                                len(fila.detalle.get("acciones", [])))
                except Exception as exc:
                    db.rollback()
                    logger.error("IMAP mandatos: fallo procesando %s: %s",
                                 correo.message_id, exc)
                    try:
                        db.add(MandatoCorreo(
                            message_id=correo.message_id, fecha=correo.fecha,
                            remitente=correo.remitente,
                            asunto=(correo.asunto or "")[:1000],
                            fuente=fuente, clasificacion="desconocido",
                            resultado="error", requiere_revision=True,
                            detalle={"error": str(exc)},
                        ))
                        db.commit()
                        vistos.add(correo.message_id)
                    except Exception:
                        db.rollback()
    finally:
        db.close()
