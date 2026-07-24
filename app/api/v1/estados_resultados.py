"""Listado de los Estados de Resultados que viven en la carpeta de Drive.

Solo lectura: expone el contenido de la carpeta para que la plataforma muestre los
archivos con su link, sin que el usuario tenga que entrar a Drive. La generación de
los ER no pasa por aquí.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.auth import get_current_user
from app.schemas.estados_resultados import ArchivosERResponse, ArchivoER, PeriodoER
from app.services.drive import (
    TIPO_CRUCE,
    TIPO_ER,
    TIPO_OTRO,
    DriveNoConfigurado,
    DriveSinAcceso,
    er_folder_id,
    listar_carpeta,
    parse_nombre_er,
)

router = APIRouter(prefix="/estados-resultados", tags=["Estados de resultados"])

_LIMITE_DEFAULT = 300
_LIMITE_MAX = 1000


@router.get("/archivos", response_model=ArchivosERResponse)
def listar_archivos(
    mes: int | None = Query(None, ge=1, le=12),
    anio: int | None = Query(None, ge=2000, le=2100),
    tipo: str | None = Query(None, description=f"{TIPO_ER} | {TIPO_CRUCE} | {TIPO_OTRO}"),
    q: str | None = Query(None, description="Filtra por texto en el nombre"),
    limite: int = Query(_LIMITE_DEFAULT, ge=1, le=_LIMITE_MAX),
    refrescar: bool = Query(False, description="Ignora el cache de 5 min"),
    _=Depends(get_current_user),
):
    """Archivos de la carpeta de ER, filtrables por período y texto.

    La carpeta tiene ~1.700 archivos, así que se filtra en el servidor: el período se
    deduce del nombre (ver `parse_nombre_er`), no de metadatos de Drive.
    """
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
    archivos = [
        {**f, **parse_nombre_er(f.get("name", ""))}
        for f in crudos
        if f.get("mimeType") != "application/vnd.google-apps.folder"
    ]

    # El filtro de tipo se aplica ANTES de contar los períodos: el selector del
    # frontend muestra esos totales, y contarlos sobre todos los tipos haría que
    # prometiera más archivos de los que la tabla puede mostrar.
    del_tipo = [a for a in archivos if a["tipo"] == tipo] if tipo else archivos

    # Períodos disponibles (para poblar los selectores del frontend), más recientes primero.
    conteo: dict[tuple[int, int], int] = {}
    for a in del_tipo:
        if a["mes"] and a["anio"]:
            conteo[(a["anio"], a["mes"])] = conteo.get((a["anio"], a["mes"]), 0) + 1
    periodos = [
        PeriodoER(mes=m, anio=y, total=n)
        for (y, m), n in sorted(conteo.items(), reverse=True)
    ]

    filtrados = del_tipo
    if mes is not None:
        filtrados = [a for a in filtrados if a["mes"] == mes]
    if anio is not None:
        filtrados = [a for a in filtrados if a["anio"] == anio]
    if q:
        needle = q.strip().lower()
        filtrados = [a for a in filtrados if needle in a.get("name", "").lower()]

    total_filtrados = len(filtrados)
    recorte = filtrados[:limite]

    return ArchivosERResponse(
        total_carpeta=len(archivos),
        total_filtrados=total_filtrados,
        truncado=total_filtrados > len(recorte),
        periodos=periodos,
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
