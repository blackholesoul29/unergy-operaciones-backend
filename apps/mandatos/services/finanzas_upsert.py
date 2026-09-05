"""Alta y actualización de un mandato de Finanzas desde la bitácora de correos."""

from datetime import date

from apps.mandatos import models as md_models


def upsert(*, proyecto, tercero, periodo, tipo, cmu, estado, comentario=None,
           fecha=None, correo_ref=None, drive_file_id=None, drive_url=None):
    """Devuelve `(mandato, creado)`.

    **El emparejamiento va primero por CMU** —es el identificador fiable y
    tolera que el nombre del proyecto o del tercero varíe entre el enviado y el
    firmado— y de RESPALDO por (proyecto, tercero, período, tipo), que cubre el
    consecutivo corregido —mismo proyecto e inversionista, otro CMU— y los
    mandatos sin CMU.

    **Nunca degrada `firmado` a `sin_firma`.** Un correo tardío no puede
    des-firmar algo que ya se firmó.
    """
    mandato = None
    if cmu:
        mandato = md_models.FinanzasMandato.objects.filter(
            cmu=cmu, periodo=periodo, tipo=tipo
        ).first()
    if mandato is None:
        mandato = md_models.FinanzasMandato.objects.filter(
            proyecto=proyecto, tercero=tercero, periodo=periodo, tipo=tipo
        ).first()

    creado = mandato is None
    if creado:
        mandato = md_models.FinanzasMandato(
            proyecto=proyecto, tercero=tercero, periodo=periodo, tipo=tipo,
            estado="sin_firma",
        )

    # Si el CMU cambió se conserva el anterior: es la pista de que hubo un
    # consecutivo corregido.
    if cmu and mandato.cmu and cmu != mandato.cmu:
        mandato.cmu_anterior = mandato.cmu
    if cmu:
        mandato.cmu = cmu
    if correo_ref:
        mandato.correo_ref = correo_ref

    hoy = fecha or date.today()
    if estado == "firmado":
        mandato.estado = "firmado"
        mandato.fecha_firma = mandato.fecha_firma or hoy
        if drive_file_id:
            mandato.drive_file_id, mandato.drive_url = drive_file_id, drive_url
    elif estado == "con_comentarios":
        # Un comentario sobre algo ya firmado no lo devuelve atrás.
        if mandato.estado != "firmado":
            mandato.estado = "con_comentarios"
        mandato.comentario = comentario
    elif estado == "corregido":
        # Se rehizo lo que la revisoría objetó: vuelve a estar en juego.
        mandato.estado = "corregido"
        mandato.comentario = None
    elif estado == "enviado_inversionista":
        mandato.estado = "enviado_inversionista"
        mandato.fecha_envio_inversionista = (
            mandato.fecha_envio_inversionista or hoy
        )
        if drive_file_id:
            mandato.drive_file_id, mandato.drive_url = drive_file_id, drive_url
    else:
        mandato.fecha_envio = mandato.fecha_envio or hoy

    mandato.save()
    return mandato, creado
