"""
Backfill histórico de páginas sin match del split O&M (OMPaginaSinMatch).

Antes del fix de persistencia, las páginas del PDF consolidado que no se
lograban emparejar a un contrato solo vivían en la respuesta HTTP del momento
del upload — no quedaba ningún rastro en base de datos. Este backfill
re-corre la detección (sin escribir ni tocar `OMDocumentoProyecto` de meses
ya facturados) sobre las facturas consolidadas ya guardadas, para poblar
`OMPaginaSinMatch` con lo que se le haya escapado a esos uploads antiguos.

Limitación conocida (no resuelta, solo comunicada): la detección corre contra
los contratos de mantenimiento ACTUALES, no contra los que existían en la
fecha del upload original. Si la lista de contratos cambió desde entonces
(nuevo proyecto registrado, nombre corregido), el resultado puede diferir de
lo que realmente pasó en su momento — es una aproximación, no una
reconstrucción exacta.
"""
from __future__ import annotations
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.contratos import ContratoServicio
from app.models.om import OMFacturaMensual, OMPaginaSinMatch
from app.services.om_pdf_splitter import detectar_paginas


def backfill_sin_match(db: Session, apply: bool = False) -> dict:
    """
    Recorre OMFacturaMensual con archivo en disco, salta períodos que ya
    tengan OMPaginaSinMatch (ya procesados por un upload posterior al fix), y
    detecta sin_match contra los contratos de mantenimiento actuales.

    Con apply=False (default) no escribe nada — solo reporta lo que haría.
    """
    contratos = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento")
        .order_by(ContratoServicio.id)
        .all()
    )
    contratos_lista = [
        {
            "contrato_id": c.id,
            "nombre_proyecto": (
                c.proyecto.nombre_comercial if c.proyecto
                else c.prestador_nombre or f"Contrato #{c.id}"
            ),
        }
        for c in contratos
    ]

    facturas = (
        db.query(OMFacturaMensual)
        .filter(OMFacturaMensual.ruta_local.isnot(None))
        .order_by(OMFacturaMensual.periodo)
        .all()
    )

    periodos_sin_archivo: list[str] = []
    periodos_saltados_ya_tenian: list[str] = []
    periodos_revisados: list[str] = []
    nuevos_sin_match: list[dict] = []

    for factura in facturas:
        ruta = Path(factura.ruta_local)
        if not ruta.exists():
            periodos_sin_archivo.append(factura.periodo)
            continue

        ya_tenia = (
            db.query(OMPaginaSinMatch)
            .filter(OMPaginaSinMatch.periodo == factura.periodo)
            .first()
        )
        if ya_tenia:
            periodos_saltados_ya_tenian.append(factura.periodo)
            continue

        periodos_revisados.append(factura.periodo)
        deteccion = detectar_paginas(ruta, contratos_lista)
        for item in deteccion["sin_match"]:
            nuevos_sin_match.append({"periodo": factura.periodo, **item})
            if apply:
                db.add(OMPaginaSinMatch(
                    periodo=factura.periodo,
                    pagina=item["pagina"],
                    nombre_extraido=item.get("nombre_extraido"),
                    estrategia=item.get("estrategia"),
                    razon=item["razon"],
                    numero_factura=item.get("numero_factura"),
                    muestra_texto=item.get("muestra_texto"),
                    origen="backfill",
                ))

    if apply:
        db.commit()

    return {
        "periodos_revisados": periodos_revisados,
        "periodos_saltados_ya_tenian": periodos_saltados_ya_tenian,
        "periodos_sin_archivo": periodos_sin_archivo,
        "nuevos_sin_match": nuevos_sin_match,
    }
