"""Escritura del enlace de Drive de un ContratoServicio o PPAContrato.

Sucesor de las columnas `ContratoServicio.enlace_drive` / `PPAContrato.carpeta_link`
(eliminadas, migracion 122): ahora es la fila tipo='contrato' de
`cliente_documentos_comerciales` para ese dueno. Los modelos exponen un
@property de solo lectura con el mismo nombre (ver models/contratos.py) para
que los schemas Out y el frontend no cambien; este modulo es el unico punto de
escritura, porque un @property no admite `setattr`.
"""
from __future__ import annotations

from app.models.clientes import ClienteDocumentoComercial


def set_enlace_documento(
    db,
    *,
    contrato_servicio_id: int | None = None,
    ppa_contrato_id: int | None = None,
    url: str | None,
    nombre: str,
) -> None:
    assert (contrato_servicio_id is None) != (ppa_contrato_id is None), \
        "exactamente un dueño (contrato_servicio_id XOR ppa_contrato_id)"

    q = db.query(ClienteDocumentoComercial).filter(ClienteDocumentoComercial.tipo == "contrato")
    q = q.filter(
        ClienteDocumentoComercial.contrato_servicio_id == contrato_servicio_id
    ) if contrato_servicio_id is not None else q.filter(
        ClienteDocumentoComercial.ppa_contrato_id == ppa_contrato_id
    )
    doc = q.first()

    url = (url or "").strip() or None
    if url is None:
        if doc:
            db.delete(doc)
        return

    if doc:
        doc.archivo_url = url
    else:
        db.add(ClienteDocumentoComercial(
            contrato_servicio_id=contrato_servicio_id,
            ppa_contrato_id=ppa_contrato_id,
            tipo="contrato",
            nombre=nombre,
            estado="firmado",
            archivo_url=url,
        ))
