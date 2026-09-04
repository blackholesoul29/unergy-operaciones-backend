"""Clasifica los routers que faltan por portar según su coste real.

Lo que decide el coste de portar un recurso no es el tamaño de su router, sino
si su capa de servicio lleva una sesión de SQLAlchemy: si no la lleva, el
servicio se mueve tal cual y solo se reescribe la capa HTTP; si la lleva, hay
que reescribirlo contra el ORM de Django.

Uso:
    PYTHONPATH=. uv run python scripts/costo_migracion_api.py
"""

import ast
import os
import re

DIR_ROUTERS = "app/api/v1"
DIR_API_NUEVA = "api/v1"

# Señales de que un módulo de servicio depende de una sesión de SQLAlchemy.
SESION = re.compile(r"\bSession\b|\bdb\s*:\s*Session|db\.query\(|db\.execute\(|db\.commit\(")

PREFIJOS_SERVICIO = ("app.services", "app.utils", "app.crud")


def ya_portado() -> set[str]:
    """Los recursos que ya existen bajo `api/v1/`."""
    if not os.path.isdir(DIR_API_NUEVA):
        return set()
    return {
        d for d in os.listdir(DIR_API_NUEVA)
        if os.path.isfile(os.path.join(DIR_API_NUEVA, d, "urls.py"))
    }


def servicios_importados(ruta: str) -> list[str]:
    try:
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
    except SyntaxError:
        return []
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module:
            if not nodo.module.startswith(PREFIJOS_SERVICIO):
                continue
            modulos.add(nodo.module)
            # `from app.services import finanzas_mandatos_service as svc` importa
            # un MÓDULO, no un nombre: sin esta línea solo se miraba
            # `app/services/__init__.py` y el servicio real quedaba sin revisar.
            for alias in nodo.names:
                modulos.add(f"{nodo.module}.{alias.name}")
        elif isinstance(nodo, ast.Import):
            for alias in nodo.names:
                if alias.name.startswith(PREFIJOS_SERVICIO):
                    modulos.add(alias.name)
    return sorted(modulos)


def usa_sesion(modulo: str) -> bool:
    for ruta in (modulo.replace(".", "/") + ".py",
                 modulo.replace(".", "/") + "/__init__.py"):
        if os.path.exists(ruta) and SESION.search(open(ruta, encoding="utf-8").read()):
            return True
    return False


def main() -> None:
    portados = ya_portado()
    filas = []
    for archivo in sorted(os.listdir(DIR_ROUTERS)):
        if not archivo.endswith(".py") or archivo in ("__init__.py", "router.py"):
            continue
        nombre = archivo[:-3]
        if nombre in portados:
            continue
        ruta = os.path.join(DIR_ROUTERS, archivo)
        fuente = open(ruta, encoding="utf-8").read()
        servicios = servicios_importados(ruta)
        filas.append({
            "recurso": nombre,
            "endpoints": len(re.findall(r"@\w*router\.(get|post|put|patch|delete)", fuente)),
            "lineas": fuente.count("\n") + 1,
            "servicios": len(servicios),
            "con_sesion": sum(1 for m in servicios if usa_sesion(m)),
        })

    mecanicos = [f for f in filas if f["con_sesion"] == 0]
    caros = [f for f in filas if f["con_sesion"] > 0]

    print(f"portados: {len(portados)}  ·  pendientes: {len(filas)}\n")
    for etiqueta, grupo in (
        ("MECÁNICOS — el servicio se mueve tal cual", mecanicos),
        ("CON REESCRITURA DE SERVICIO a ORM de Django", caros),
    ):
        total = sum(f["endpoints"] for f in grupo)
        print(f"=== {etiqueta}: {len(grupo)} recursos, {total} endpoints ===")
        print(f"{'recurso':24}{'endp':>6}{'líneas':>8}{'svc con sesión':>16}")
        for f in sorted(grupo, key=lambda f: (f["con_sesion"], f["lineas"])):
            marca = f'{f["con_sesion"]}/{f["servicios"]}'
            print(f'{f["recurso"]:24}{f["endpoints"]:6}{f["lineas"]:8}{marca:>16}')
        print()


if __name__ == "__main__":
    main()
