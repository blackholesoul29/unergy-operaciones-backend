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

    Filtra el archivo a solo las plantas de Unergy (las que hacen match
    contra el snapshot de fronteras de SU PROPIO mes, por columna
    FechaDocumento) y les agrega nombre/tipo/MW. Los códigos de otros
    agentes del mercado se descartan, no se dejan en blanco — igual que
    hacía el notebook original.
    Devuelve (df_filtrado_y_enriquecido, codigos_sin_match: set).

    Vectorizado con Series.map en vez de df.iterrows(): con archivos de
    cientos de miles de filas (ej. grip de un mes completo), iterrows()
    tarda decenas de segundos y bloquea el proceso — con un solo hilo
    (el que también atiende las peticiones HTTP de polling), eso hace
    que la pestaña web vea timeouts aunque la descarga siga viva.
    """
    if columna_codigo not in df.columns:
        raise ValueError(
            f"El archivo no tiene la columna '{columna_codigo}' necesaria para "
            f"enriquecer este tipo — no se puede filtrar por planta Unergy."
        )
    meses_dato = df["FechaDocumento"].astype(str).str.slice(0, 7)
    # fillna("") ANTES de astype(str): en pandas 3.0 el nuevo dtype string
    # preserva los vacíos como NaN (float) incluso tras .astype(str), y esos
    # NaN terminaban en sin_match mezclando float+str, lo que rompía el
    # sorted() del orquestador ("'<' not supported between float and str").
    # Los archivos de XM traen filas de totales/footer con el código vacío.
    codigos = df[columna_codigo].fillna("").astype(str).str.strip()
    claves = meses_dato + "|" + codigos

    tabla_combinada = {
        f"{mes}|{codigo}": info
        for mes, tabla in fronteras_por_mes.items()
        for codigo, info in tabla.items()
    }
    info_por_fila = claves.map(tabla_combinada)
    coincide = info_por_fila.notna()

    # Solo códigos reales sin match; se ignoran los vacíos (footer/totales).
    sin_match = {c for c in codigos[~coincide] if c}

    df = df[coincide].copy()
    info_coincidente = info_por_fila[coincide]
    df["Nombre de la Frontera"] = info_coincidente.map(lambda x: x["nombre"])
    df["Tipo de Frontera"] = info_coincidente.map(lambda x: x["tipo"])
    df["Capacidad efectiva [MW]"] = info_coincidente.map(lambda x: x["mw"])

    return df, sin_match
