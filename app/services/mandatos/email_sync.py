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
