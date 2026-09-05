"""Escritura del enlace de Drive de un contrato de servicio o de un PPA.

Sucesor de las columnas `ContratoServicio.enlace_drive` y
`PpaContrato.carpeta_link` (eliminadas en la migración 122): hoy es la fila
`tipo='contrato'` de `cliente_documentos_comerciales` para ese dueño.

Los modelos exponen una propiedad de solo lectura con el mismo nombre para que
el JSON y el frontend no cambien; **este módulo es el único punto de
escritura**, porque a una propiedad no se le puede hacer `setattr`.
"""

from apps.clientes import models as cl_models

TIPO = "contrato"


def set_enlace(
    *,
    contrato_servicio_id: int | None = None,
    ppa_contrato_id: int | None = None,
    url: str | None,
    nombre: str,
) -> None:
    """Crea, actualiza o BORRA el enlace. Exactamente un dueño.

    Una URL vacía borra la fila en vez de guardar cadena vacía: así la
    propiedad de lectura devuelve `None` y el frontend no muestra un enlace
    roto.
    """
    if (contrato_servicio_id is None) == (ppa_contrato_id is None):
        raise ValueError(
            "exactamente un dueño (contrato_servicio_id XOR ppa_contrato_id)"
        )

    consulta = cl_models.ClienteDocumentoComercial.objects.filter(tipo=TIPO)
    if contrato_servicio_id is not None:
        consulta = consulta.filter(contrato_servicio_id=contrato_servicio_id)
    else:
        consulta = consulta.filter(ppa_contrato_id=ppa_contrato_id)

    url = (url or "").strip() or None
    if url is None:
        consulta.delete()
        return

    documento = consulta.first()
    if documento is not None:
        documento.archivo_url = url
        documento.save(update_fields=["archivo_url"])
        return

    cl_models.ClienteDocumentoComercial.objects.create(
        contrato_servicio_id=contrato_servicio_id,
        ppa_contrato_id=ppa_contrato_id,
        tipo=TIPO,
        nombre=nombre,
        estado="firmado",
        archivo_url=url,
    )
