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
from app.services.mandatos_service import TRANSICIONES, extraer_cmu_de_nombre, transicion_valida

logger = logging.getLogger("mandatos.email_sync")

FUENTE_REVISORIA = "revisoria"
FUENTE_ENVIO = "envio_inversionista"

REMITENTE_REVISORIA = "vlondono@jbp.com.co"
REMITENTE_ENVIO = "jessica@unergy.io"

_PDF_DIR = Path("uploads/mandatos")

# Mismo límite que upload-firmado (app/api/v1/mandatos.py) para el subido manual.
_TAMANO_MAX_ADJUNTO_BYTES = 20 * 1024 * 1024


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


def _es_terminal(estado: str) -> bool:
    """Un estado es terminal cuando la máquina no permite ninguna salida."""
    return not TRANSICIONES.get(estado)


def elegir_mandato(candidatos: list) -> tuple:
    """Candidatos de un mismo CMU (ya cargados de la BD) → (mandato, motivo).

    El correo nunca dice a qué período pertenece el CMU, así que no se
    adivina cuando hay más de un período "en curso" para el mismo CMU (bug
    real: julio queda con_correcciones y agosto enviado_revisoria; una
    corrección tardía de julio no debe aplicarse sobre agosto solo porque es
    el período más nuevo). Pura: decide solo entre los objetos recibidos, no
    consulta nada.

      - sin candidatos                       → (None, "cmu_no_encontrado")
      - un único candidato no terminal       → (ese candidato, None)
      - más de un candidato no terminal      → (None, "periodo_ambiguo")
      - todos los candidatos son terminales  → (el más reciente, None) --
        se deja que transicion_valida() lo rechace más adelante, así sale
        como "transicion_invalida" en vez de silenciarse acá.
    """
    if not candidatos:
        return None, "cmu_no_encontrado"
    no_terminales = [c for c in candidatos if not _es_terminal(c.estado)]
    if len(no_terminales) == 1:
        return no_terminales[0], None
    if len(no_terminales) > 1:
        return None, "periodo_ambiguo"
    return max(candidatos, key=lambda c: c.periodo), None


def planear_transicion(estado_previo: str, destino: str) -> list[str] | None:
    """Camino de estados a recorrer, o None si no hay uno válido.

    Normalmente es un solo paso ([destino]). La única excepción deliberada:
    un PDF de envío a inversionista es evidencia de que el mandato fue
    firmado, así que desde enviado_revisoria o corregido se encadena
    firmado → enviado_inversionista en una sola operación. Desde
    con_correcciones NO se encadena -- enviarle a un inversionista un
    mandato con observaciones abiertas es una anomalía que debe verse, no
    resolverse sola -- por eso ese caso cae al chequeo normal de
    transicion_valida() y devuelve None.

    Una lista vacía (no None) significa "válido, no hay nada que cambiar"
    (estado_previo ya es destino).
    """
    cadena = [destino]
    if destino == "enviado_inversionista" and estado_previo in ("enviado_revisoria", "corregido"):
        cadena = ["firmado", "enviado_inversionista"]

    camino: list[str] = []
    estado = estado_previo
    for paso in cadena:
        if estado == paso:
            continue
        if not transicion_valida(estado, paso):
            return None
        camino.append(paso)
        estado = paso
    return camino


def _guardar_adjunto(nombre: str, contenido: bytes) -> str | None:
    """Guarda el adjunto dentro de _PDF_DIR. Devuelve la ruta, o None si el
    nombre no es seguro.

    `nombre` viene del header MIME de un correo de un remitente externo, así
    que no se confía en él: igual que asociar_pdf() en app/api/v1/mandatos.py,
    se usa solo su basename (Path(nombre).name descarta cualquier "../" u
    otro segmento de directorio) y se verifica que la ruta resultante siga
    contenida en _PDF_DIR, para que un nombre de archivo malicioso no pueda
    escribir fuera del directorio de subidas.
    """
    _PDF_DIR.mkdir(parents=True, exist_ok=True)
    destino = _PDF_DIR / Path(nombre).name
    try:
        destino.resolve().relative_to(_PDF_DIR.resolve())
    except ValueError:
        return None
    destino.write_bytes(contenido)
    return str(destino)


def _aplicar_accion(db: Session, accion: dict, correo: CorreoCrudo, fuente: str) -> dict:
    """Aplica una acción a su mandato. Devuelve el registro para `detalle`.

    Nunca fuerza una transición: si la máquina de estados no la permite, o si
    el período del CMU es ambiguo, se registra el conflicto y el mandato
    queda como estaba. El registro guarda, además de estado_previo, el valor
    anterior de cada campo que sí llegó a tocar -- así revertir_correo()
    (app/api/v1/mandatos.py) puede deshacerlos todos, no solo el estado.
    """
    cmu = accion["cmu"]
    # El correo no dice a qué período pertenece el CMU: se cargan TODOS los
    # candidatos de ese CMU y se elige entre ellos sin adivinar (elegir_mandato).
    candidatos = db.execute(select(Mandato).where(Mandato.cmu == cmu)).scalars().all()
    m, motivo = elegir_mandato(candidatos)
    if motivo == "cmu_no_encontrado":
        return {"cmu": cmu, "resultado": "cmu_no_encontrado"}
    if motivo == "periodo_ambiguo":
        periodos = sorted(c.periodo.isoformat() for c in candidatos if not _es_terminal(c.estado))
        return {"cmu": cmu, "resultado": "periodo_ambiguo", "periodos": periodos}

    destino = accion["estado_destino"]
    estado_previo = m.estado
    fecha_correo = correo.fecha.date()

    camino = planear_transicion(estado_previo, destino)
    if camino is None:
        return {"cmu": cmu, "resultado": "transicion_invalida",
                "estado_previo": estado_previo, "estado_destino": destino}

    registro = {"cmu": cmu, "resultado": "aplicado", "mandato_id": m.id,
                "estado_previo": estado_previo,
                "estado_nuevo": camino[-1] if camino else estado_previo}

    if accion["adjunto"]:
        contenido = dict(correo.adjuntos).get(accion["adjunto"])
        if contenido:
            if len(contenido) > _TAMANO_MAX_ADJUNTO_BYTES:
                return {"cmu": cmu, "resultado": "adjunto_demasiado_grande",
                        "adjunto": accion["adjunto"]}
            ruta = _guardar_adjunto(accion["adjunto"], contenido)
            if ruta is None:
                return {"cmu": cmu, "resultado": "adjunto_nombre_invalido",
                        "adjunto": accion["adjunto"]}
            registro["pdf_firmado_ruta_previo"] = m.pdf_firmado_ruta
            registro["pdf_firmado_nombre_previo"] = m.pdf_firmado_nombre
            m.pdf_firmado_ruta = ruta
            m.pdf_firmado_nombre = Path(ruta).name

    if camino:
        m.estado = camino[-1]
    if accion["observacion"]:
        registro["observacion_previa"] = m.observacion
        m.observacion = accion["observacion"]
    if ("firmado" in camino or destino == "firmado") and m.fecha_firmado is None:
        registro["fecha_firmado_previa"] = None
        m.fecha_firmado = fecha_correo
    if destino == "enviado_inversionista":
        registro["fecha_envio_inversionista_previa"] = (
            m.fecha_envio_inversionista.isoformat() if m.fecha_envio_inversionista else None
        )
        registro["correo_ref_envio_previo"] = m.correo_ref_envio
        m.fecha_envio_inversionista = fecha_correo
        m.correo_ref_envio = correo.message_id
    if fuente == FUENTE_REVISORIA:
        registro["correo_ref_revisoria_previo"] = m.correo_ref_revisoria
        m.correo_ref_revisoria = correo.message_id

    return registro


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
