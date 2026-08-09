"""Listado y descarga de los Estados de Resultados que viven en la carpeta de Drive.

Solo lectura: expone el contenido de la carpeta para que la plataforma muestre los
archivos, los abra y los descargue, sin que el usuario tenga que entrar a Drive (ni
tener permisos sobre ella: el service account es el que lee). La generación de los
ER no pasa por aquí.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.v1.auth import get_current_user
from app.schemas.estados_resultados import ArchivosERResponse, ArchivoER, PeriodoER
from app.services.drive import (
    TIPO_CRUCE,
    TIPO_ER,
    TIPO_OTRO,
    DriveNoConfigurado,
    DriveSinAcceso,
    construir_zip,
    descargar_archivo,
    er_folder_id,
    filtrar_archivos,
    listar_carpeta,
    parse_nombre_er,
)

router = APIRouter(prefix="/estados-resultados", tags=["Estados de resultados"])

_LIMITE_DEFAULT = 300
_LIMITE_MAX = 1000
# Tope de la descarga masiva. Los archivos pesan ~9 KB, así que 600 son ~6 MB: el
# límite es por el tiempo de bajarlos de Drive uno por uno, no por el peso.
_ZIP_MAX_ARCHIVOS = 600
_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cargar(refrescar: bool = False) -> list[dict]:
    """Archivos de la carpeta, ya parseados. Traduce los errores de Drive a HTTP."""
    try:
        crudos = listar_carpeta(er_folder_id(), usar_cache=not refrescar)
    except DriveNoConfigurado:
        raise HTTPException(500, "Google Drive no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON)")
    except DriveSinAcceso:
        raise HTTPException(
            502,
            "Sin acceso a la carpeta de Drive. Compártela con el service account "
            "como lector (client_email de GOOGLE_SERVICE_ACCOUNT_JSON).",
        )
    # Se ignoran subcarpetas: la vista lista archivos, no navega el árbol.
    return [
        {**f, **parse_nombre_er(f.get("name", ""))}
        for f in crudos
        if f.get("mimeType") != "application/vnd.google-apps.folder"
    ]


@router.get("/archivos", response_model=ArchivosERResponse)
def listar_archivos(
    mes: int | None = Query(None, ge=1, le=12),
    anio: int | None = Query(None, ge=2000, le=2100),
    tipo: str | None = Query(None, description=f"{TIPO_ER} | {TIPO_CRUCE} | {TIPO_OTRO}"),
    version: str | None = Query(None, description="Solo cruce de facturas: txf, tx3…tx8"),
    q: str | None = Query(None, description="Filtra por texto en el nombre"),
    limite: int = Query(_LIMITE_DEFAULT, ge=1, le=_LIMITE_MAX),
    refrescar: bool = Query(False, description="Ignora el cache de 5 min"),
    _=Depends(get_current_user),
):
    """Archivos de la carpeta de ER, filtrables por tipo, período, versión y texto.

    La carpeta tiene ~1.700 archivos, así que se filtra en el servidor: el período y
    la versión se deducen del nombre (ver `parse_nombre_er`), no de metadatos de Drive.
    """
    archivos = _cargar(refrescar)

    # El filtro de tipo se aplica ANTES de contar los períodos y las versiones: el
    # frontend muestra esos totales en sus selectores, y contarlos sobre todos los
    # tipos haría que prometieran más archivos de los que la tabla puede mostrar.
    del_tipo = filtrar_archivos(archivos, tipo=tipo)

    conteo: dict[tuple[int, int], int] = {}
    for a in del_tipo:
        if a["mes"] and a["anio"]:
            conteo[(a["anio"], a["mes"])] = conteo.get((a["anio"], a["mes"]), 0) + 1
    periodos = [
        PeriodoER(mes=m, anio=y, total=n)
        for (y, m), n in sorted(conteo.items(), reverse=True)
    ]

    # Versiones realmente presentes (hoy txf y tx3; el rango va hasta tx8). Se
    # calculan de los datos para que aparezcan solas cuando se empiecen a usar.
    versiones = sorted({(a["version"] or "").lower() for a in del_tipo if a["version"]})

    filtrados = filtrar_archivos(del_tipo, mes=mes, anio=anio, version=version, q=q)
    total_filtrados = len(filtrados)
    recorte = filtrados[:limite]

    return ArchivosERResponse(
        total_carpeta=len(archivos),
        total_filtrados=total_filtrados,
        truncado=total_filtrados > len(recorte),
        periodos=periodos,
        versiones=versiones,
        archivos=[
            ArchivoER(
                id=a["id"],
                nombre=a.get("name", ""),
                tipo=a["tipo"],
                descripcion=a["descripcion"],
                mes=a["mes"],
                anio=a["anio"],
                version=a["version"],
                modificado=a.get("modifiedTime"),
                tamano=int(a["size"]) if a.get("size") else None,
                link=a.get("webViewLink"),
                es_copia=a["es_copia"],
            )
            for a in recorte
        ],
    )


def _content_disposition(nombre: str) -> str:
    """Nombre de archivo seguro para la cabecera (los nombres traen tildes y comas)."""
    ascii_fallback = nombre.encode("ascii", "ignore").decode() or "descarga.xlsx"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(nombre)}"


@router.get("/archivos/{file_id}/descargar")
def descargar(file_id: str, _=Depends(get_current_user)):
    """Descarga un archivo de la carpeta, proxeado por el service account.

    Se valida que el id pertenezca a la carpeta de ER: el service account puede leer
    otros shared drives (soportes del Panel, adjuntos de fallas), y sin esta
    comprobación el endpoint sería un proxy abierto a todo lo que él ve.
    """
    archivo = next((a for a in _cargar() if a["id"] == file_id), None)
    if not archivo:
        raise HTTPException(404, "El archivo no está en la carpeta de estados de resultados")
    try:
        data = descargar_archivo(file_id)
    except DriveNoConfigurado:
        raise HTTPException(500, "Google Drive no configurado")
    except DriveSinAcceso:
        raise HTTPException(502, "Sin acceso al archivo en Drive")
    return Response(
        content=data,
        media_type=_MIME_XLSX,
        headers={"Content-Disposition": _content_disposition(archivo.get("name") or "archivo.xlsx")},
    )


@router.get("/archivos-zip")
def descargar_zip(
    mes: int | None = Query(None, ge=1, le=12),
    anio: int | None = Query(None, ge=2000, le=2100),
    tipo: str | None = Query(None),
    version: str | None = Query(None),
    q: str | None = Query(None),
    _=Depends(get_current_user),
):
    """Descarga en un ZIP todos los archivos que pasan los filtros.

    Usa el mismo `filtrar_archivos` que el listado, así que el ZIP trae exactamente
    lo que el usuario ve en la tabla.
    """
    seleccion = filtrar_archivos(_cargar(), tipo=tipo, mes=mes, anio=anio, version=version, q=q)
    if not seleccion:
        raise HTTPException(404, "No hay archivos que coincidan con los filtros")
    if len(seleccion) > _ZIP_MAX_ARCHIVOS:
        raise HTTPException(
            413,
            f"Son {len(seleccion)} archivos y el máximo por ZIP es {_ZIP_MAX_ARCHIVOS}. "
            "Filtra por período o versión.",
        )
    try:
        data = construir_zip(seleccion)
    except DriveNoConfigurado:
        raise HTTPException(500, "Google Drive no configurado")

    partes = ["estados_resultados" if tipo == TIPO_ER else "cruce_facturas" if tipo == TIPO_CRUCE else "archivos"]
    if anio and mes:
        partes.append(f"{anio}-{mes:02d}")
    if version:
        partes.append(version.lower())
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition("_".join(partes) + ".zip")},
    )
