"""Flujo editorial de los informes: estados, comentarios y composición.

Tres cosas que no son obvias y por eso viven acá y no en la vista:

1. **Un portafolio no guarda el HTML de sus miembros**: lo compone al vuelo
   desde los informes individuales del mismo período. Así, editar un individual
   se refleja solo en el portafolio.
2. **El flujo de estados es una máquina**, no un campo libre: `borrador →
   revisado → aprobado`, y solo el verificador puede aprobar o reabrir.
3. **Los comentarios devuelven el informe a borrador.** Un comentario nuevo
   sobre algo «revisado» lo baja, y subsanar el último lo vuelve a subir.
"""

import uuid
from datetime import datetime, timezone

from apps.plataforma import models as pl_models

# Correos con permisos especiales del flujo editorial.
EMAIL_VERIFICADOR = "juan.jose@unergy.io"
EMAILS_VERIFICADOR = {EMAIL_VERIFICADOR, "juanjose@unergy.io"}
EMAIL_REMITENTE = "laura.h@unergy.io"

TRANSICIONES = {
    "borrador": ("revisado",),
    "revisado": ("aprobado", "borrador"),
    # Reabrir un aprobado: solo verificador o admin.
    "aprobado": ("borrador",),
}

# Separador de páginas que usa el frontend al unir el informe.
SEPARADOR_PAGINA = '<div class="rpt-page-sep"></div>'


class TransicionInvalida(ValueError):
    pass


class SinPermiso(PermissionError):
    pass


class Conflicto(RuntimeError):
    pass


def es_verificador(usuario) -> bool:
    return (
        (usuario.email or "").lower() in EMAILS_VERIFICADOR
        or (usuario.rol or "") == "admin"
    )


def es_remitente(usuario) -> bool:
    """El verificador también puede enviar: si no, el flujo se atasca."""
    return es_verificador(usuario) or (
        (usuario.email or "").lower() == EMAIL_REMITENTE
    )


# ---------------------------------------------------------------------------
# Composición del portafolio
# ---------------------------------------------------------------------------

def _marcar_seccion(html: str, sub_project: str) -> str:
    """Marca la página con `data-sub-project` para el write-back del editor.

    Idempotente: si ya viene marcada —un individual que se editó antes desde el
    portafolio— no la duplica.
    """
    if not html or not sub_project:
        return html or ""
    if "data-sub-project=" in html[:300]:
        return html
    return html.replace(
        '<div class="rpt-page">',
        f'<div class="rpt-page" data-sub-project="{sub_project}">',
        1,
    )


def individual_de(sub_project: str, desde: str, hasta: str):
    """El informe individual (`op`) de un proyecto para ese mismo período."""
    if not sub_project:
        return None
    return pl_models.InformeGuardado.objects.filter(
        tipo="op", sub_project=sub_project,
        periodo_desde=desde, periodo_hasta=hasta,
    ).first()


def componer(informe) -> str:
    """El HTML completo de un portafolio: consolidada + una página por miembro.

    Por cada miembro se prefiere el informe individual VIVO; solo si el proyecto
    no tiene uno guardado se usa el `html_inline` congelado en el miembro. Ese
    orden es lo que hace que editar un individual actualice el portafolio.
    """
    partes = [informe.html_content or ""]
    miembros = sorted(
        (m for m in (informe.miembros or []) if isinstance(m, dict)),
        key=lambda m: m.get("orden", 0),
    )
    for miembro in miembros:
        sub_project = miembro.get("sub_project")
        individual = individual_de(
            sub_project, informe.periodo_desde, informe.periodo_hasta
        )
        if individual and individual.html_content:
            partes.append(
                _marcar_seccion(individual.html_content, sub_project)
            )
        elif miembro.get("html_inline"):
            partes.append(
                _marcar_seccion(miembro["html_inline"], sub_project)
            )
    return SEPARADOR_PAGINA.join(p for p in partes if p)


def html_para_enviar(informe) -> str:
    return componer(informe) if informe.tipo == "port" else (
        informe.html_content or ""
    )


# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------

def cambiar_estado(informe, nuevo: str, usuario) -> None:
    if nuevo not in TRANSICIONES.get(informe.estado, ()):
        raise TransicionInvalida(
            f"Transición inválida: {informe.estado} → {nuevo}"
        )

    if nuevo == "aprobado" and not es_verificador(usuario):
        raise SinPermiso(
            "Sólo el verificador autorizado (Juan José) puede aprobar informes."
        )
    if (
        informe.estado == "aprobado" and nuevo == "borrador"
        and not es_verificador(usuario)
    ):
        raise SinPermiso(
            "Sólo el verificador autorizado puede reabrir un informe ya aprobado."
        )

    if nuevo == "aprobado":
        pendientes = [
            c for c in (informe.comentarios or []) if not c.get("resuelto")
        ]
        if pendientes:
            raise Conflicto(
                f"No se puede aprobar: hay {len(pendientes)} comentario(s) "
                "sin subsanar."
            )

    ahora = datetime.now(timezone.utc)
    era_aprobado = informe.estado == "aprobado"
    informe.estado = nuevo
    campos = ["estado"]

    if nuevo == "aprobado":
        informe.aprobado_por_id = usuario.id
        informe.aprobado_por_nombre = usuario.nombre
        informe.aprobado_en = ahora
        campos += ["aprobado_por", "aprobado_por_nombre", "aprobado_en"]
    elif nuevo == "revisado":
        # Quien marca «revisado» queda como editor.
        informe.editado_por_id = usuario.id
        informe.editado_por_nombre = usuario.nombre
        informe.editado_en = ahora
        campos += ["editado_por", "editado_por_nombre", "editado_en"]
    elif nuevo == "borrador" and era_aprobado:
        informe.aprobado_por_id = None
        informe.aprobado_por_nombre = None
        informe.aprobado_en = None
        campos += ["aprobado_por", "aprobado_por_nombre", "aprobado_en"]

    informe.save(update_fields=campos)


# ---------------------------------------------------------------------------
# Comentarios
# ---------------------------------------------------------------------------

def agregar_comentario(informe, mensaje: str, usuario) -> None:
    if informe.estado == "aprobado":
        raise Conflicto(
            "El informe ya fue aprobado; no se aceptan más comentarios. "
            "Reábrelo antes."
        )
    limpio = (mensaje or "").strip()
    if not limpio:
        raise ValueError("El mensaje del comentario no puede estar vacío")

    comentarios = list(informe.comentarios or [])
    comentarios.append({
        "id": str(uuid.uuid4()),
        "autor_email": usuario.email or "",
        "autor_nombre": usuario.nombre or "",
        "mensaje": limpio,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resuelto": False,
        "resuelto_en": None,
        "resuelto_por_email": None,
        "resuelto_por_nombre": None,
        "respuesta": None,
    })
    informe.comentarios = comentarios
    campos = ["comentarios"]
    # Un comentario nuevo sobre algo revisado lo devuelve a borrador.
    if informe.estado == "revisado":
        informe.estado = "borrador"
        campos.append("estado")
    informe.save(update_fields=campos)


def resolver_comentario(informe, comentario_id: str, respuesta, usuario) -> None:
    comentarios = list(informe.comentarios or [])
    objetivo = next(
        (c for c in comentarios if c.get("id") == comentario_id), None
    )
    if objetivo is None:
        raise LookupError("Comentario no encontrado")
    if objetivo.get("resuelto"):
        raise Conflicto("Este comentario ya fue marcado como subsanado")

    objetivo["resuelto"] = True
    objetivo["resuelto_en"] = datetime.now(timezone.utc).isoformat()
    objetivo["resuelto_por_email"] = usuario.email or ""
    objetivo["resuelto_por_nombre"] = usuario.nombre or ""
    if respuesta and respuesta.strip():
        objetivo["respuesta"] = respuesta.strip()

    informe.comentarios = comentarios
    campos = ["comentarios"]
    # Subsanado el último, el informe vuelve solo a «revisado».
    if all(c.get("resuelto") for c in comentarios) and informe.estado == "borrador":
        informe.estado = "revisado"
        informe.editado_por_id = usuario.id
        informe.editado_por_nombre = usuario.nombre
        informe.editado_en = datetime.now(timezone.utc)
        campos += ["estado", "editado_por", "editado_por_nombre", "editado_en"]
    informe.save(update_fields=campos)


def borrar_comentario(informe, comentario_id: str, usuario) -> None:
    comentarios = list(informe.comentarios or [])
    objetivo = next(
        (c for c in comentarios if c.get("id") == comentario_id), None
    )
    if objetivo is None:
        raise LookupError("Comentario no encontrado")
    if (
        objetivo.get("autor_email", "").lower() != (usuario.email or "").lower()
        and (usuario.rol or "") != "admin"
    ):
        raise SinPermiso(
            "Sólo el autor del comentario (o admin) puede eliminarlo"
        )
    informe.comentarios = [
        c for c in comentarios if c.get("id") != comentario_id
    ]
    informe.save(update_fields=["comentarios"])


# ---------------------------------------------------------------------------
# Borrado
# ---------------------------------------------------------------------------

def congelar_en_portafolios(informe) -> None:
    """Antes de borrar un individual, congela su HTML en los portafolios.

    Borrar un individual NO debe hacer desaparecer su sección de los
    portafolios que lo incluyen: se copia su contenido al `html_inline` del
    miembro (solo si estaba vacío) para que la sección siga apareciendo.
    """
    if informe.tipo != "op":
        return
    portafolios = pl_models.InformeGuardado.objects.filter(
        tipo="port",
        periodo_desde=informe.periodo_desde,
        periodo_hasta=informe.periodo_hasta,
    )
    for portafolio in portafolios:
        miembros = list(portafolio.miembros or [])
        cambio = False
        for miembro in miembros:
            if (
                isinstance(miembro, dict)
                and miembro.get("sub_project") == informe.sub_project
                and not miembro.get("html_inline")
            ):
                miembro["html_inline"] = informe.html_content
                cambio = True
        if cambio:
            portafolio.miembros = miembros
            portafolio.save(update_fields=["miembros"])
