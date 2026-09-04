"""A qué correos se le notifica de un proyecto o de un cliente.

Solo la parte que necesita el módulo de informes; el resto de
`app/services/contactos.py` se portará con los recursos que lo usen.
"""

from datetime import date

from django.db.models import Q

from apps.clientes import models as cl_models
from apps.proyectos import models as py_models


def correos(tipo: str, *, proyecto_id=None, cliente_id=None) -> list[str]:
    """Correos de ese tipo. Exactamente uno de `proyecto_id` o `cliente_id`.

    Para un proyecto hay dos caminos y el orden importa:

    1. Si el proyecto tiene un **puntero de área** para ese tipo, se usa SOLO el
       cliente al que apunta. Es la forma de decir «para operación, escríbanle a
       este y a nadie más».
    2. Si no lo tiene, se usa la unión de los contactos de todos sus
       inversionistas VIGENTES, sin duplicados.
    """
    if cliente_id is not None:
        return list(
            cl_models.Contacto.objects
            .filter(
                cliente_id=cliente_id, tipo=tipo, recibe_notificaciones=True
            )
            .values_list("email", flat=True)
        )

    if proyecto_id is None:
        return []

    puntero = (
        cl_models.ProyectoAreaContacto.objects
        .filter(proyecto_id=proyecto_id, tipo=tipo)
        .values_list("cliente_id", flat=True).first()
    )
    if puntero:
        return correos(tipo, cliente_id=puntero)

    hoy = date.today()
    inversionistas = (
        py_models.ProyectoInversionista.objects
        .filter(proyecto_id=proyecto_id)
        # Vigente = sin fecha de fin, o con una que aún no pasó.
        .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=hoy))
        .values_list("cliente_id", flat=True)
    )

    salida: list[str] = []
    vistos_cliente: set[int] = set()
    for cliente in inversionistas:
        if not cliente or cliente in vistos_cliente:
            continue
        vistos_cliente.add(cliente)
        salida.extend(correos(tipo, cliente_id=cliente))

    # Un mismo correo puede llegar por dos inversionistas distintos.
    vistos: set[str] = set()
    return [
        e for e in salida
        if e and not (e in vistos or vistos.add(e))
    ]


def proyecto_ids_por_cliente(tipo: str, cliente_id: int) -> list[int]:
    """Inverso de `correos`: proyectos donde `cliente_id` es la fuente de contacto.

    Por puntero de área, o por ser inversionista vigente en un proyecto que no
    tiene puntero de ese tipo — el puntero manda, igual que en `correos`.
    """
    con_override = cl_models.ProyectoAreaContacto.objects.filter(tipo=tipo)
    override_ids = set(
        con_override.filter(cliente_id=cliente_id).values_list("proyecto_id", flat=True)
    )
    proyectos_con_algun_override = set(
        con_override.values_list("proyecto_id", flat=True)
    )

    hoy = date.today()
    inversionista_ids = {
        pid for pid in py_models.ProyectoInversionista.objects
        .filter(cliente_id=cliente_id)
        .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=hoy))
        .values_list("proyecto_id", flat=True)
        if pid not in proyectos_con_algun_override
    }

    return list(override_ids | inversionista_ids)
