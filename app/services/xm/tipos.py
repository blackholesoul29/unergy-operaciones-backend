"""Config de tipos de archivo XM soportados por la Descarga de XM.

Rutas confirmadas por la usuaria y por xm.py/aenc_reporte.py (ver spec).
"""

RUTA_PUBLICA = "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/{anio}-{mes:02d}"
RUTA_PRIVADA = "/INFORMACION_XM/USUARIOSK/UNGG/SIC/COMERCIA/{anio}-{mes:02d}"

TIPOS_CONFIG = {
    "dspcttos": {"ruta": "privada", "patron": "diario"},
    "aenc":     {"ruta": "privada", "patron": "diario"},
    "BalCttos": {"ruta": "privada", "patron": "diario"},
    "grip":     {"ruta": "publica", "patron": "diario"},
    "arrpas":   {"ruta": "publica", "patron": "diario"},
    "tgrl":     {"ruta": "publica", "patron": "diario"},
    "trsd":     {"ruta": "publica", "patron": "diario"},
    "cxcsb":    {"ruta": "publica", "patron": "mensual"},
}

# Tipos cuyo archivo trae código SIC de planta y se puede enriquecer con
# nombre + MW desde el snapshot mensual de fronteras del FTP.
TIPOS_ENRIQUECIBLES = {"grip", "arrpas", "tgrl", "cxcsb"}

# Columna del archivo XM que trae el código SIC de planta, según tipo.
COLUMNA_CODIGO_ENRIQUECIMIENTO = {
    "grip": "PLANTA",
    "tgrl": "PLANTA",
    "arrpas": "SUBMERCADO",
    "cxcsb": "SUBMERCADO",
}


class TipoXMInvalido(ValueError):
    pass


def validar_tipo(tipo: str) -> None:
    if tipo not in TIPOS_CONFIG:
        raise TipoXMInvalido(f"Tipo de archivo XM no soportado: {tipo}")


def es_mensual(tipo: str) -> bool:
    validar_tipo(tipo)
    return TIPOS_CONFIG[tipo]["patron"] == "mensual"


def ruta_directorio(tipo: str, anio: int, mes: int) -> str:
    validar_tipo(tipo)
    plantilla = RUTA_PUBLICA if TIPOS_CONFIG[tipo]["ruta"] == "publica" else RUTA_PRIVADA
    return plantilla.format(anio=anio, mes=mes)


def nombre_archivo(tipo: str, extension: str, anio: int, mes: int, dia: int | None = None) -> str:
    validar_tipo(tipo)
    if es_mensual(tipo):
        return f"{tipo}{mes:02d}.{extension.lower()}"
    if dia is None:
        raise ValueError(f"El tipo '{tipo}' requiere día (patrón diario)")
    return f"{tipo}{mes:02d}{dia:02d}.{extension.lower()}"
