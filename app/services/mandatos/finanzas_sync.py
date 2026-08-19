"""Correo → qué escribir en finanzas_mandatos.

Compone piezas ya probadas: el parser de Fase B interpreta el texto, el detector
de firmas mira el PDF, el servicio de Finanzas escribe. Acá solo se decide.

`decidir_finanzas` es pura: recibe un correo y un verificador de firmas
inyectado, y devuelve qué habría que hacer. No consulta la base ni escribe
archivos, para poder probar las reglas sin montar un arnés.
"""
from __future__ import annotations

import logging
from datetime import date

from app.services.finanzas_mandatos_service import (
    extraer_periodo_de_asunto, tipo_de_nombre,
)
from app.services.mandatos.adjuntos import expandir_adjuntos
from app.services.mandatos.email_parser import (
    CLASIF_MOLDE_SIMPLE, clasificar_correo, extraer_observaciones,
    extraer_pa_del_cuerpo,
)
from app.services.mandatos.firmas import verificar_firmas
from app.services.mandatos.imap_client import CorreoCrudo
from app.services.mandatos_service import parsear_nombre_zip

logger = logging.getLogger("mandatos.finanzas_sync")

FUENTE_REVISORIA = "revisoria"
FUENTE_ENVIO = "envio_inversionista"


def _identidad(nombre_archivo: str, correo: CorreoCrudo) -> dict | None:
    """(cmu, proyecto, tercero, tipo, periodo) o None si falta algo.

    El tercero NO está en el nombre del archivo cuando el mandante es un P.A.:
    sale del cuerpo. Si falta el tercero o el período, se devuelve None en vez de
    completar con un valor por defecto -- la identidad es la llave única de la
    tabla, y una identidad inventada crea una fila fantasma que después nadie
    reconoce ni limpia.
    """
    parsed = parsear_nombre_zip(nombre_archivo)
    if not parsed:
        return None
    periodo = extraer_periodo_de_asunto(correo.asunto or "", correo.fecha.date())
    if not periodo:
        return None
    pa = extraer_pa_del_cuerpo(correo.cuerpo)
    tercero = parsed["inversionista"] or (pa["nombre"] if pa else "")
    if not tercero:
        return None
    return {
        "cmu": parsed["cmu"],
        "proyecto": parsed["proyecto"],
        "tercero": tercero,
        "tipo": tipo_de_nombre(nombre_archivo),
        "periodo": periodo,
        "pa_codigo": pa["codigo"] if pa else None,
    }


def decidir_finanzas(correo: CorreoCrudo, fuente: str, *, verificador=verificar_firmas) -> dict:
    """{'clasificacion', 'acciones', 'requiere_revision', 'sin_identidad'}.

    `verificador` se inyecta para poder probar sin PDFs reales.
    """
    adjuntos = expandir_adjuntos(list(correo.adjuntos))
    acciones: list[dict] = []
    sin_identidad: list[str] = []
    clasificacion = clasificar_correo(correo.asunto, correo.cuerpo)

    for nombre, contenido in adjuntos:
        if not nombre.lower().endswith(".pdf"):
            continue
        parsed = parsear_nombre_zip(nombre)
        if not parsed:
            sin_identidad.append(nombre)
            continue
        firmas = verificador(contenido)
        if fuente == FUENTE_ENVIO:
            # Jessica manda al inversionista lo que ya está firmado, y su correo
            # SÍ trae el P.A., así que se puede armar la identidad completa y
            # crear la fila si no existe.
            ident = _identidad(nombre, correo)
            if not ident:
                sin_identidad.append(nombre)
                continue
            acciones.append({**ident, "estado": "enviado_inversionista",
                             "adjunto": nombre, "firmas": firmas, "comentario": None})
        elif firmas["estado"] == "firmado_completo":
            # Los correos de la revisoría NO traen el P.A. -- verificado contra
            # los tres fixtures reales: extraer_pa_del_cuerpo devuelve None en
            # todos. Así que acá no se construye identidad, se busca la que ya
            # existe por CMU (ver _aplicar). Inventar un tercero vacío crearía
            # una fila paralela a la real y partiría el mandato en dos.
            acciones.append({"cmu": parsed["cmu"], "proyecto": parsed["proyecto"],
                             "tipo": tipo_de_nombre(nombre), "tercero": None,
                             "periodo": None, "pa_codigo": None, "estado": "firmado",
                             "adjunto": nombre, "firmas": firmas, "comentario": None})
        else:
            # Llegó el PDF pero no está firmado (o no se pudo verificar). No se
            # marca firmado por el mero hecho de que haya adjunto: manda el
            # documento, no el sobre.
            sin_identidad.append(f"{nombre} ({firmas['estado']})")

    # Observaciones de texto, solo si el correo encaja en el molde conocido.
    if fuente == FUENTE_REVISORIA and clasificacion == CLASIF_MOLDE_SIMPLE:
        con_pdf = {a["cmu"] for a in acciones}
        for obs in extraer_observaciones(correo.cuerpo):
            if obs["cmu"] in con_pdf:
                continue
            # Sin adjunto no hay nombre de archivo, así que no hay proyecto ni
            # tipo: la acción sale incompleta y el aplicador la resuelve por CMU
            # contra lo que ya exista en la tabla.
            acciones.append({"cmu": obs["cmu"], "estado": "con_comentarios",
                             "comentario": obs["observacion"], "adjunto": None,
                             "proyecto": None, "tercero": None, "tipo": None,
                             "periodo": None, "pa_codigo": None, "firmas": None})

    requiere = bool(sin_identidad) or (
        fuente == FUENTE_REVISORIA and clasificacion != CLASIF_MOLDE_SIMPLE)
    return {"clasificacion": clasificacion, "acciones": acciones,
            "requiere_revision": requiere, "sin_identidad": sin_identidad}
