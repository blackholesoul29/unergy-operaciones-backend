"""Lo que Quoia (Gaia) sabe de las fronteras.

Quoia es la fuente de los borders y de los datos de medidor. Este módulo
envuelve al cliente y traduce sus respuestas; **nunca crea fronteras solo**: los
borders detectados se muestran como pendientes y alguien los confirma.
"""

import logging

logger = logging.getLogger("operaciones.fronteras")

CATEGORIA_POR_CAMPO = (
    ("frt_generation", "generacion"),
    ("frt_consumption", "consumo"),
)

_cliente = None


class QuoiaNoConfigurado(RuntimeError):
    pass


class QuoiaNoResponde(RuntimeError):
    pass


def cliente():
    global _cliente
    if _cliente is None:
        from app.services.mgs.gaia_client import GaiaClient

        _cliente = GaiaClient()
    if not _cliente.enabled:
        raise QuoiaNoConfigurado(
            "Credenciales de Gaia/Quoia no configuradas (GAIA_USER/GAIA_PASS)"
        )
    return _cliente


def borders():
    """Todos los borders de Quoia. Levanta si la consulta FALLÓ.

    Sin este chequeo, una caída de Quoia se veía igual que «todo ya está
    registrado»: lista vacía y 200 OK (diagnóstico de Fronteras, 2026-08-24).
    """
    gaia = cliente()
    datos = gaia.get_all_borders()
    if gaia.ultima_llamada_fallo:
        raise QuoiaNoResponde(
            "No se pudo consultar Quoia -- intenta de nuevo en un momento"
        )
    return datos


def iterar_frt(lista):
    """`(frt_code, categoría, nombre, metadatos)` de cada border."""
    for border in lista:
        nombre = (border.get("name") or "").strip()
        for campo, categoria in CATEGORIA_POR_CAMPO:
            frt = border.get(campo)
            if not frt:
                continue
            codigo = (frt.get("frt_code") or "").strip()
            # Quoia a veces carga un marcador tipo "N/A" cuando el border aún
            # no tiene código real. No es usable, y la barra rompería la ruta
            # al confirmar, porque el código va en la URL.
            if not codigo or "/" in codigo:
                continue
            yield codigo.lower(), categoria, nombre, frt


def info_de_medidores(frt_code: str):
    """`(principal, respaldo)` con marca, modelo y serie. Nunca levanta."""
    from app.services.mgs.gaia_client import get_frt_meter_info

    try:
        return get_frt_meter_info(cliente(), frt_code)
    except Exception:
        # «Lo mejor que se pueda»: no tener el dato del medidor no debe
        # impedir crear la frontera.
        logger.debug("no se pudo leer el medidor de %s", frt_code, exc_info=True)
        return None, None


def completar_medidores(frontera) -> list[str]:
    """Rellena los datos de medidor que FALTEN, desde Quoia.

    Devuelve los campos tocados. No pisa nada que ya venga en el cuerpo: se
    completa, no se sobrescribe.
    """
    if not frontera.codigo_frontera:
        return []
    principal, respaldo = info_de_medidores(frontera.codigo_frontera)
    tocados = []
    for info, sufijo in ((principal, "ppal"), (respaldo, "resp")):
        if not info:
            continue
        for clave, campo in (
            ("marca", f"marca_med_{sufijo}"),
            ("modelo", f"modelo_med_{sufijo}"),
            ("serie", f"nro_serie_med_{sufijo}"),
        ):
            if getattr(frontera, campo, None) is None and info.get(clave):
                setattr(frontera, campo, info[clave])
                tocados.append(campo)
    return tocados


def fijar_medidores(frontera, principal, respaldo) -> None:
    """Escribe los datos de medidor SIN preguntar si ya había.

    Al confirmar un border desde Quoia sí manda Quoia: es el momento en que se
    registra la frontera y su dato es el bueno.
    """
    for info, sufijo in ((principal, "ppal"), (respaldo, "resp")):
        if not info:
            continue
        setattr(frontera, f"marca_med_{sufijo}", info.get("marca"))
        setattr(frontera, f"modelo_med_{sufijo}", info.get("modelo"))
        setattr(frontera, f"nro_serie_med_{sufijo}", info.get("serie"))
