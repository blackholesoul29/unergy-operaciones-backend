"""Forma canónica de la ficha del informe.

El frontend manda checklists parciales, y la lectura da por hecho que todas las
claves existen. Estas funciones rellenan la forma completa al guardar y al leer,
que es lo único que aportaban los modelos anidados de Pydantic del backend
anterior.
"""

ELABORADO_POR_DEFECTO = "Operaciones Unergy"
ACTIVIDAD_POR_DEFECTO = "Puesta en marcha del sistema de monitoreo"

_ITEM = {"estado": None, "nota": None}
_ITEM_CON_EVIDENCIA = {**_ITEM, "evidencia": []}

FORMA = {
    "checklist_fusion_solar": {
        "starlink": _ITEM_CON_EVIDENCIA,
        "datos_coherentes": _ITEM,
        "evidencia": [],
        "nota": None,
        "inversores": [],
    },
    "checklist_frontera": {
        "principal": _ITEM_CON_EVIDENCIA,
        "respaldo": _ITEM_CON_EVIDENCIA,
    },
    "checklist_estacion_meteo": {
        "instalacion": _ITEM,
        "en_plataforma": _ITEM,
        "reporta_datos": _ITEM_CON_EVIDENCIA,
        "poa": _ITEM,
        "temperatura_ambiente": _ITEM,
        "velocidad_viento": _ITEM,
        "direccion_viento": _ITEM,
    },
    "checklist_reconectador": {
        "tiene": None,
        "en_plataforma": _ITEM,
        "calidad_datos": _ITEM,
        "evidencia": [],
        "nota": None,
    },
}


def _completar(recibido, plantilla):
    """Rellena las claves que falten, sin pisar las que vienen."""
    if not isinstance(recibido, dict):
        return {k: _copia(v) for k, v in plantilla.items()}
    salida = dict(recibido)
    for clave, valor in plantilla.items():
        if clave not in salida:
            salida[clave] = _copia(valor)
        elif isinstance(valor, dict):
            salida[clave] = _completar(salida[clave], valor)
    return salida


def _copia(valor):
    if isinstance(valor, dict):
        return dict(valor)
    if isinstance(valor, list):
        return list(valor)
    return valor


def normalizar(datos: dict) -> dict:
    """Deja los cuatro checklist con todas sus claves antes de guardar."""
    salida = dict(datos)
    for campo, plantilla in FORMA.items():
        salida[campo] = _completar(salida.get(campo), plantilla)
    return salida


def leer(ficha) -> dict:
    """La ficha lista para el JSON, con sus valores por defecto aplicados."""
    from api.v1.informe_om.serializers import JSONB_DICT, JSONB_LISTA

    if ficha is None:
        base = {campo: {} for campo in JSONB_DICT}
        base.update({campo: [] for campo in JSONB_LISTA})
        base.update({
            "version": None,
            "elaborado_por": ELABORADO_POR_DEFECTO,
            "actividad": ACTIVIDAD_POR_DEFECTO,
            "estado": "borrador",
            "empresa_contratista": None,
            "fecha_energizacion": None,
            "fecha_inicio_operacion": None,
            "conclusion": None,
        })
        return normalizar(base)

    datos = {
        "version": ficha.version,
        "elaborado_por": ficha.elaborado_por or ELABORADO_POR_DEFECTO,
        "actividad": ficha.actividad or ACTIVIDAD_POR_DEFECTO,
        "estado": ficha.estado or "borrador",
        "empresa_contratista": ficha.empresa_contratista,
        "fecha_energizacion": ficha.fecha_energizacion,
        "fecha_inicio_operacion": ficha.fecha_inicio_operacion,
        "conclusion": ficha.conclusion,
    }
    for campo in JSONB_DICT:
        datos[campo] = getattr(ficha, campo) or {}
    for campo in JSONB_LISTA:
        datos[campo] = getattr(ficha, campo) or []
    return normalizar(datos)
