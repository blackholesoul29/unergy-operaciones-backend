"""Carga y armado del listado de archivos de ER.

No consulta la base: la "consulta" es a la API de Drive. El módulo se llama
`queryset.py` igual que en los demás recursos para que el sitio donde buscar la
lectura de datos sea siempre el mismo.
"""

from rest_framework.exceptions import APIException, ValidationError

from apps.contabilidad.services import drive

CARPETA_NO_CONFIGURADA = (
    "Google Drive no configurado (falta GOOGLE_SERVICE_ACCOUNT_JSON)"
)
SIN_ACCESO = (
    "Sin acceso a la carpeta de Drive. Compártela con el service account "
    "como lector (client_email de GOOGLE_SERVICE_ACCOUNT_JSON)."
)


class DriveNoConfigurado(APIException):
    status_code = 500
    default_detail = CARPETA_NO_CONFIGURADA


class DriveSinAcceso(APIException):
    status_code = 502
    default_detail = SIN_ACCESO


def cargar(refrescar: bool = False) -> list[dict]:
    """Archivos de la carpeta, ya parseados. Traduce los errores de Drive a HTTP."""
    try:
        crudos = drive.listar_carpeta(drive.er_folder_id(), usar_cache=not refrescar)
    except drive.DriveNoConfigurado:
        raise DriveNoConfigurado()
    except drive.DriveSinAcceso:
        raise DriveSinAcceso()
    # Se ignoran las subcarpetas: la vista lista archivos, no navega el árbol.
    return [
        {**f, **drive.parse_nombre_er(f.get("name", ""))}
        for f in crudos
        if f.get("mimeType") != "application/vnd.google-apps.folder"
    ]


def build_listado(archivos: list[dict], filtros: dict, limite: int) -> dict:
    """El listado con sus selectores de período y versión.

    El filtro de TIPO se aplica antes de contar períodos y versiones: el
    frontend muestra esos totales en sus selectores, y contarlos sobre todos los
    tipos haría que prometieran más archivos de los que la tabla puede mostrar.
    """
    del_tipo = drive.filtrar_archivos(archivos, tipo=filtros.get("tipo"))

    conteo: dict[tuple[int, int], int] = {}
    for archivo in del_tipo:
        if archivo["mes"] and archivo["anio"]:
            clave = (archivo["anio"], archivo["mes"])
            conteo[clave] = conteo.get(clave, 0) + 1
    periodos = [
        {"mes": mes, "anio": anio, "total": total}
        for (anio, mes), total in sorted(conteo.items(), reverse=True)
    ]

    # Las versiones se calculan de los datos (hoy txf y tx3; el rango llega a
    # tx8) para que aparezcan solas cuando se empiecen a usar.
    versiones = sorted(
        {(a["version"] or "").lower() for a in del_tipo if a["version"]}
    )

    filtrados = drive.filtrar_archivos(del_tipo, **_sin_tipo(filtros))
    recorte = filtrados[:limite]

    return {
        "total_carpeta": len(archivos),
        "total_filtrados": len(filtrados),
        "truncado": len(filtrados) > len(recorte),
        "periodos": periodos,
        "versiones": versiones,
        "archivos": [
            {
                "id": a["id"],
                "nombre": a.get("name", ""),
                "tipo": a["tipo"],
                "descripcion": a["descripcion"],
                "mes": a["mes"],
                "anio": a["anio"],
                "version": a["version"],
                "modificado": a.get("modifiedTime"),
                "tamano": int(a["size"]) if a.get("size") else None,
                "link": a.get("webViewLink"),
                "es_copia": a["es_copia"],
            }
            for a in recorte
        ],
    }


def _sin_tipo(filtros: dict) -> dict:
    return {k: v for k, v in filtros.items() if k != "tipo"}


def leer_filtros(params) -> dict:
    """Valida y normaliza los filtros de la query string."""
    def entero(nombre, minimo, maximo):
        crudo = params.get(nombre)
        if crudo in (None, ""):
            return None
        if not crudo.lstrip("-").isdigit():
            raise ValidationError({nombre: "Debe ser un entero."})
        valor = int(crudo)
        if not minimo <= valor <= maximo:
            raise ValidationError({nombre: f"Entre {minimo} y {maximo}."})
        return valor

    return {
        "mes": entero("mes", 1, 12),
        "anio": entero("anio", 2000, 2100),
        "tipo": params.get("tipo") or None,
        "version": params.get("version") or None,
        "q": params.get("q") or None,
    }
