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


def _aplicar(db, accion: dict, correo: CorreoCrudo) -> dict:
    """Aplica una acción y devuelve su registro para la bitácora.

    La validación de transiciones vive acá y no en upsert_mandato: esa función
    la sigue usando el script de Jessica por /ingest, y meterle una regla nueva
    podría rechazar algo que ella hace hoy. La red de seguridad va donde está la
    automatización.
    """
    from app.models.finanzas_mandatos import FinanzasMandato
    from app.services import finanzas_mandatos_service as svc
    from app.services.finanzas_mandatos_service import transicion_firma_valida

    if not accion.get("periodo"):
        # Todo lo que viene de la revisoría cae acá: sus correos no traen el
        # P.A., así que no hay identidad que construir y hay que encontrar la
        # fila que ya existe. Aplica tanto a las observaciones de texto como a
        # los PDF firmados.
        #
        # Si no existe la fila, NO se crea: significaría que llegó firmado algo
        # que la plataforma nunca vio salir. Eso es justo la anomalía que la
        # reconciliación reporta como sin_registro_de_envio, y taparla creando
        # una fila incompleta la volvería invisible.
        existente = (db.query(FinanzasMandato)
                     .filter(FinanzasMandato.cmu == accion["cmu"])
                     .order_by(FinanzasMandato.periodo.desc()).first())
        if not existente:
            return {"cmu": accion["cmu"], "resultado": "cmu_no_encontrado"}
        destino = accion["estado"]
        if not transicion_firma_valida(existente.estado, destino):
            return {"cmu": accion["cmu"], "resultado": "transicion_invalida",
                    "estado_previo": existente.estado, "estado_destino": destino}
        previo = existente.estado
        existente.estado = destino
        if accion.get("comentario") is not None:
            existente.comentario = accion["comentario"]
        existente.correo_ref = correo.message_id
        if destino == "firmado":
            existente.fecha_firma = existente.fecha_firma or correo.fecha.date()
        if accion.get("adjunto") and not existente.drive_url:
            contenido = dict(expandir_adjuntos(list(correo.adjuntos))).get(accion["adjunto"])
            if contenido:
                from app.services.finanzas_mandatos_drive import subir_pdf
                sub = f"{existente.periodo.strftime('%Y-%m')}-{existente.tipo}"
                res = subir_pdf(contenido, accion["adjunto"], sub)
                existente.drive_file_id, existente.drive_url = res["id"], res["url"]
        return {"cmu": accion["cmu"], "resultado": "aplicado", "id": existente.id,
                "estado_previo": previo, "estado_nuevo": destino,
                "pdf_ya_en_drive": bool(accion.get("adjunto") and existente.drive_url)}

    existente = (db.query(FinanzasMandato)
                 .filter(FinanzasMandato.proyecto == accion["proyecto"],
                         FinanzasMandato.tercero == accion["tercero"],
                         FinanzasMandato.periodo == accion["periodo"],
                         FinanzasMandato.tipo == accion["tipo"]).first())
    previo = existente.estado if existente else None
    destino = accion["estado"]
    if existente and not transicion_firma_valida(previo, destino):
        return {"cmu": accion["cmu"], "resultado": "transicion_invalida",
                "estado_previo": previo, "estado_destino": destino}

    # No re-subir lo que ya está en Drive. `subir_pdf` siempre hace
    # files().create(): no deduplica ni por nombre ni por contenido. Sin esta
    # guarda, la primera corrida (que barre 30 días hacia atrás, ~93 correos)
    # volvería a subir todos los PDFs que el script de Jessica ya subió, dejando
    # duplicados en Drive y apuntando cada fila a la copia nueva en vez de la
    # original. Limpiar eso después es trabajo manual archivo por archivo.
    #
    # Si algún día hace falta reemplazar un PDF ya guardado (una reexpedición,
    # por ejemplo), se hace explícitamente -- no como efecto colateral de
    # reprocesar un correo viejo.
    drive_id = drive_url = None
    ya_tenia_pdf = bool(existente and existente.drive_url)
    if accion.get("adjunto") and not ya_tenia_pdf:
        contenido = dict(expandir_adjuntos(list(correo.adjuntos))).get(accion["adjunto"])
        if contenido:
            from app.services.finanzas_mandatos_drive import subir_pdf
            sub = f"{accion['periodo'].strftime('%Y-%m')}-{accion['tipo']}"
            res = subir_pdf(contenido, accion["adjunto"], sub)
            drive_id, drive_url = res["id"], res["url"]

    m, creado = svc.upsert_mandato(
        db, proyecto=accion["proyecto"], tercero=accion["tercero"],
        periodo=accion["periodo"], tipo=accion["tipo"], cmu=accion["cmu"],
        estado=destino, comentario=accion.get("comentario"),
        fecha=correo.fecha.date(), correo_ref=correo.message_id,
        drive_file_id=drive_id, drive_url=drive_url)
    return {"cmu": accion["cmu"], "resultado": "aplicado", "id": m.id,
            "pdf_ya_en_drive": ya_tenia_pdf,
            "creado": creado, "estado_previo": previo, "estado_nuevo": destino}


def procesar_correo_finanzas(db, correo: CorreoCrudo, fuente: str):
    """Procesa un correo y devuelve su fila de bitácora, sin commit."""
    from app.models.mandatos import MandatoCorreo

    d = decidir_finanzas(correo, fuente)
    registros = [_aplicar(db, a, correo) for a in d["acciones"]]
    aplicado = any(r["resultado"] == "aplicado" for r in registros)
    problema = any(r["resultado"] != "aplicado" for r in registros)
    return MandatoCorreo(
        message_id=correo.message_id, fecha=correo.fecha,
        remitente=(correo.remitente or "")[:255],
        asunto=(correo.asunto or "")[:1000], fuente=fuente,
        clasificacion=d["clasificacion"],
        resultado="aplicado" if aplicado else "omitido",
        requiere_revision=d["requiere_revision"] or problema,
        detalle={"acciones": registros, "sin_identidad": d["sin_identidad"]})
