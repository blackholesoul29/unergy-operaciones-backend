"""Escritura del enlace de Drive de un ContratoServicio o un PpaContrato.

Puerto de `app/services/documentos.py`.

Sucesor de las columnas `ContratoServicio.enlace_drive` y
`PpaContrato.carpeta_link` (eliminadas en la revisión 122): hoy el enlace es la
fila `tipo='contrato'` de `cliente_documentos_comerciales` para ese dueño. La
lectura se expone con el mismo nombre para que el frontend no cambie; **este
módulo es el único punto de escritura**.
"""

from __future__ import annotations

from apps.clientes.models import ClienteDocumentoComercial


def set_enlace_documento(*, contrato_servicio_id: int | None = None,
                         ppa_contrato_id: int | None = None,
                         url: str | None, nombre: str) -> None:
    assert (contrato_servicio_id is None) != (ppa_contrato_id is None), \
        "exactamente un dueño (contrato_servicio_id XOR ppa_contrato_id)"

    dueno = (
        {"contrato_servicio_id": contrato_servicio_id}
        if contrato_servicio_id is not None
        else {"ppa_contrato_id": ppa_contrato_id}
    )
    doc = ClienteDocumentoComercial.objects.filter(tipo="contrato", **dueno).first()

    url = (url or "").strip() or None
    if url is None:
        # Vaciar el enlace BORRA la fila: dejarla con `archivo_url` en NULL sería
        # un documento sin documento.
        if doc:
            doc.delete()
        return

    if doc:
        doc.archivo_url = url
        doc.save(update_fields=["archivo_url"])
    else:
        ClienteDocumentoComercial.objects.create(
            **dueno, tipo="contrato", nombre=nombre, estado="firmado", archivo_url=url,
        )
