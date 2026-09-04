"""Catálogo de empresas responsables de los contratos PPA.

«Responsable» es de quién es el contrato: Unergy o un tercero. Lo que hace con
la bandera `incluir_en_cumplimiento` es decidir si ese contrato entra o no en la
matriz de cumplimiento.
"""

import unicodedata

from django.db.models import Count, Q

from apps.ppa import models as ppa_models

# Contratos de los que Unergy NO es responsable (confirmado el 2026-08-08).
# Solo se usa para la clasificación INICIAL; después se administra desde la UI.
CONTRATOS_EXTERNOS = (
    "BIA Delta 1", "BIA Naos 1", "BIA Naos 2", "BIA Naos 3", "BIA Polaris 1",
    "Sol&Cielo7", "Sol&Cielo9",
)


class NombreDuplicado(ValueError):
    pass


class TieneContratos(RuntimeError):
    pass


def clave(texto: str | None) -> str:
    """Clave de comparación tolerante: sin tildes y sin nada que no sea alfanumérico.

    Empareja "Sol&Cielo7" con "SOL&CIELO 7", pero NO con "sol y cielo7": solo
    ignora los símbolos, no los traduce.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return "".join(c for c in sin_tildes.lower() if c.isalnum())


def con_conteo():
    """El catálogo con cuántos contratos VIVOS tiene cada responsable."""
    return ppa_models.PpaResponsable.objects.annotate(
        n_contratos=Count(
            "contratos",
            filter=Q(contratos__deleted_at__isnull=True),
        )
    ).order_by("nombre")


def validar_nombre_libre(nombre: str, excepto_id: int | None = None) -> str:
    limpio = (nombre or "").strip()
    if not limpio:
        raise ValueError("El nombre del responsable no puede estar vacío")
    consulta = ppa_models.PpaResponsable.objects.filter(nombre__iexact=limpio)
    if excepto_id is not None:
        consulta = consulta.exclude(pk=excepto_id)
    if consulta.exists():
        raise NombreDuplicado(f'Ya existe un responsable llamado "{limpio}"')
    return limpio


def contratos_vivos(responsable_id: int) -> int:
    return ppa_models.PpaContrato.objects.filter(
        responsable_id=responsable_id, deleted_at__isnull=True
    ).count()


def borrar(responsable) -> None:
    """Se BLOQUEA si aún tiene contratos.

    Reasignarlos primero deja explícito qué pasa con ellos: el
    `ON DELETE SET NULL` los volvería visibles en la matriz de cumplimiento sin
    que nadie se entere.
    """
    cuantos = contratos_vivos(responsable.id)
    if cuantos:
        raise TieneContratos(
            f'No se puede eliminar "{responsable.nombre}": tiene {cuantos} '
            "contrato(s). Reasígnalos a otro responsable primero."
        )
    responsable.delete()


def asignar(contrato_ids: list[int], responsable_id: int | None) -> int:
    """Asigna (o desasigna con `None`) el responsable de varios contratos."""
    if not contrato_ids:
        return 0
    return ppa_models.PpaContrato.objects.filter(
        pk__in=contrato_ids, deleted_at__isnull=True
    ).update(responsable_id=responsable_id)


def sembrar(clasificar: bool = True) -> dict:
    """Crea el catálogo base y clasifica los contratos UNA sola vez.

    Idempotente, y la clasificación es de un solo disparo: en cuanto algún
    contrato ya tiene responsable no se vuelve a tocar ninguna asignación. Un
    redespliegue no debe revertir lo que alguien cambió a mano en la UI.
    """
    catalogo = {}
    for nombre, incluir in (("Unergy", True), ("Externo", False)):
        catalogo[nombre], _ = ppa_models.PpaResponsable.objects.get_or_create(
            nombre=nombre, defaults={"incluir_en_cumplimiento": incluir}
        )

    reporte = {"unergy": 0, "externo": 0, "sin_match": [], "clasifico": False}
    ya_clasificado = ppa_models.PpaContrato.objects.filter(
        responsable__isnull=False
    ).exists()
    if not clasificar or ya_clasificado:
        return reporte

    externos = {clave(n): n for n in CONTRATOS_EXTERNOS}
    encontrados: set[str] = set()
    for contrato in ppa_models.PpaContrato.objects.filter(deleted_at__isnull=True):
        coincide = next(
            (
                k for k in (
                    clave(contrato.nombre_interno),
                    clave(contrato.numero_codigo_contrato),
                )
                if k and k in externos
            ),
            None,
        )
        if coincide:
            contrato.responsable = catalogo["Externo"]
            encontrados.add(coincide)
            reporte["externo"] += 1
        else:
            contrato.responsable = catalogo["Unergy"]
            reporte["unergy"] += 1
        contrato.save(update_fields=["responsable"])

    reporte["clasifico"] = True
    reporte["sin_match"] = [
        n for k, n in externos.items() if k not in encontrados
    ]
    return reporte
