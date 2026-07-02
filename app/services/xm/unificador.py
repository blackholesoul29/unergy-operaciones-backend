"""Unificación de archivos XM (misma lógica que Unificacion.ipynb) y
enriquecimiento opcional con datos de planta Unergy."""
import io
from datetime import date

import pandas as pd


def encoding_para(tipo: str) -> str:
    return "latin1" if tipo == "aenc" else "utf-8-sig"


def leer_csv(contenido: bytes, tipo: str) -> pd.DataFrame:
    encoding = encoding_para(tipo)
    try:
        return pd.read_csv(io.BytesIO(contenido), sep=";", encoding=encoding)
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(contenido), sep=";", encoding="latin1")


def unificar(tipo: str, archivos: list[tuple[str, bytes]]) -> pd.DataFrame:
    """archivos: [(fecha_documento, contenido_bytes), ...] ya en orden."""
    dataframes = []
    for fecha_documento, contenido in archivos:
        df = leer_csv(contenido, tipo)
        df.insert(0, "FechaDocumento", fecha_documento)
        dataframes.append(df)
    if not dataframes:
        return pd.DataFrame()
    return pd.concat(dataframes, ignore_index=True)


def nombre_salida(tipo: str, extension: str, fecha_inicio: date, fecha_fin: date) -> tuple[str, str]:
    if fecha_inicio.month == fecha_fin.month and fecha_inicio.year == fecha_fin.year:
        sufijo = f"{fecha_inicio.month:02d}"
    else:
        sufijo = f"{fecha_inicio.month:02d}-{fecha_fin.month:02d}"
    base = f"{tipo}_{extension.lower()}_{sufijo}"
    return f"{base}.xlsx", f"{base}.{extension.lower()}"


def exportar(df: pd.DataFrame) -> tuple[bytes, bytes]:
    buf_xlsx = io.BytesIO()
    df.to_excel(buf_xlsx, index=False, engine="openpyxl")
    buf_xlsx.seek(0)

    buf_txt = io.BytesIO()
    df.to_csv(buf_txt, sep=";", index=False, encoding="utf-8-sig")
    buf_txt.seek(0)

    return buf_xlsx.read(), buf_txt.read()


def enriquecer(df: pd.DataFrame, tipo: str, fronteras_por_mes: dict, columna_codigo: str):
    """fronteras_por_mes: {'YYYY-MM': {codigo: {nombre, tipo, mw}}, ...}.

    Cada fila se enriquece con el snapshot de fronteras de SU PROPIO mes
    (columna FechaDocumento), no uno solo para todo el rango.
    Devuelve (df_enriquecido, codigos_sin_match: set).
    """
    nombres, tipos_frontera, mws = [], [], []
    sin_match = set()

    for _, fila in df.iterrows():
        mes_dato = str(fila["FechaDocumento"])[:7]
        tabla = fronteras_por_mes.get(mes_dato, {})
        codigo = str(fila[columna_codigo]).strip()
        info = tabla.get(codigo)
        if info:
            nombres.append(info["nombre"])
            tipos_frontera.append(info["tipo"])
            mws.append(info["mw"])
        else:
            nombres.append(None)
            tipos_frontera.append(None)
            mws.append(None)
            sin_match.add(codigo)

    df = df.copy()
    df["Nombre de la Frontera"] = nombres
    df["Tipo de Frontera"] = tipos_frontera
    df["Capacidad efectiva [MW]"] = mws
    return df, sin_match
