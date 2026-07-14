"""Snapshot mensual de fronteras comerciales del FTP de XM.

El enriquecimiento de grip/arrpas/tgrl/cxcsb usa el ÚLTIMO archivo
UNGG_FronterasComerciales_DD-MM-YYYY.xlsx disponible en el mes del dato
(no la tabla `fronteras` de la BD, que no guarda histórico por período).
Ver docs/superpowers/specs/2026-07-02-descarga-xm-design.md sección 4.
"""
import io
import logging

logger = logging.getLogger(__name__)

FRONTERAS_DIR = "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/{anio}-{mes:02d}"
FRONTERAS_PREFIJO = "UNGG_FronterasComerciales_"
HOJA = "Fronteras Comerciales"


def carpeta_fronteras(anio: int, mes: int) -> str:
    return FRONTERAS_DIR.format(anio=anio, mes=mes)


def elegir_ultimo_archivo(nombres: list[str]) -> str | None:
    """Los nombres empiezan por DD-MM-YYYY dentro de una carpeta de mes fijo,
    así que ordenar alfabéticamente da el día más reciente."""
    candidatos = sorted(
        n for n in nombres
        if n.startswith(FRONTERAS_PREFIJO) and n.lower().endswith(".xlsx")
    )
    return candidatos[-1] if candidatos else None


def parsear_fronteras_xlsx(contenido: bytes) -> dict:
    """Devuelve {codigo_sic_submercado_exportador: {nombre, tipo, mw}}.

    Lee por nombre de columna (no por índice fijo) para no romper si XM
    reordena columnas.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    ws = wb[HOJA]
    filas = ws.iter_rows(values_only=True)
    header = next(filas)

    idx = {}
    for i, h in enumerate(header):
        if not h:
            continue
        h_norm = str(h).strip()
        if "Submercado Exportador" in h_norm:
            idx["codigo"] = i
        elif h_norm == "Nombre de la Frontera":
            idx["nombre"] = i
        elif h_norm == "Tipo de Frontera":
            idx["tipo"] = i
        elif h_norm.startswith("Capacidad efectiva"):
            idx["mw"] = i

    faltantes = {"codigo", "nombre", "tipo", "mw"} - idx.keys()
    if faltantes:
        raise ValueError(f"Columnas no encontradas en el Excel de fronteras: {sorted(faltantes)}")

    resultado = {}
    for fila in filas:
        codigo = fila[idx["codigo"]]
        if not codigo:
            continue
        resultado[str(codigo).strip()] = {
            "nombre": fila[idx["nombre"]],
            "tipo": fila[idx["tipo"]],
            "mw": fila[idx["mw"]],
        }
    return resultado


def obtener_fronteras_mes(listar_fn, descargar_fn, anio: int, mes: int, max_retroceso: int = 3):
    """Busca el último archivo de fronteras del mes pedido; si esa carpeta
    no tiene archivos, retrocede mes a mes hasta `max_retroceso` veces.

    `listar_fn(directorio) -> list[str]` y `descargar_fn(directorio, nombre) -> bytes`
    se inyectan para poder testear sin FTP real; en producción son
    wrappers sobre `ftp_client.listar_directorio`/`descargar_bytes`.

    Devuelve (tabla, mes_usado: 'YYYY-MM' | None, archivo_usado: str | None).
    """
    a, m = anio, mes
    for _ in range(max_retroceso + 1):
        directorio = carpeta_fronteras(a, m)
        logger.info("Buscando snapshot de fronteras en %s", directorio)
        nombres = listar_fn(directorio)
        archivo = elegir_ultimo_archivo(nombres)
        if archivo:
            logger.info("Usando snapshot de fronteras: %s", archivo)
            contenido = descargar_fn(directorio, archivo)
            return parsear_fronteras_xlsx(contenido), f"{a:04d}-{m:02d}", archivo
        logger.info("Sin snapshot de fronteras en %s, retrocediendo un mes", directorio)
        m -= 1
        if m == 0:
            m, a = 12, a - 1
    logger.warning("No se encontró ningún snapshot de fronteras tras %d meses de retroceso", max_retroceso)
    return {}, None, None
