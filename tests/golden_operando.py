"""Herramientas del golden test de `GET /comercial/proyectos-operando`.

Es la precondición de la Fase 4 del refactor (`06-plan-migracion.md` §7.1): esa
fase cambia de dónde lee `app/services/comercial.py` y **la salida tiene que
quedar idéntica**. La única forma de demostrarlo es tener capturada la respuesta
de antes.

Este módulo no captura nada -- eso lo hace `scripts/capturar_golden_operando.py`
contra una API viva. Acá vive lo que se puede probar sin base de datos: el
comparador y los tres invariantes de `05-impacto-campos-congelados.md` §4.

Por qué un comparador propio y no `==`: un `assert base == actual` dice "son
distintos" y nada más. Sobre un árbol de 34 PPA × N plantas × ~60 campos, eso no
sirve para arreglar nada. Este devuelve la ruta exacta de cada diferencia.
"""
from __future__ import annotations

# Los cuatro campos de `energia_promedio_detalle`, que solo se llenan cuando el
# promedio es medido o manual (app/services/comercial.py:_gen_promedio).
CAMPOS_DETALLE = ("dias_con_datos", "ventana_desde", "ventana_hasta", "actualizado_en")

# Orígenes que NO pueden traer detalle: no hay ventana de medición detrás.
ORIGENES_SIN_DETALLE = ("estimado", "declarado")


def _ordenable(lista: list) -> list:
    """Ordena una lista de dicts por su id, si todos lo tienen.

    El golden compara posición por posición, así que un cambio de orden en la
    respuesta se vería como si hubieran cambiado todos los elementos. Si los
    elementos tienen id, el orden deja de importar.
    """
    if lista and all(isinstance(x, dict) and x.get("id") is not None for x in lista):
        return sorted(lista, key=lambda x: (str(type(x["id"])), str(x["id"])))
    return lista


def comparar(base, actual, ruta: str = "") -> list[str]:
    """Las diferencias entre dos capturas, con la ruta de cada una."""
    difs: list[str] = []

    # `None` frente a un valor NO se reporta como cambio de tipo sino como
    # cambio de valor: es el caso de `operador_red_id` rellenándose, y leerlo
    # como "NoneType → int" esconde justo lo que importa.
    if base is None or actual is None:
        return [] if base is actual else [f"{ruta or '(raíz)'}: {base!r} → {actual!r}"]

    if type(base) is not type(actual) and not (
        isinstance(base, (int, float)) and isinstance(actual, (int, float))
    ):
        return [f"{ruta or '(raíz)'}: cambió el tipo, {type(base).__name__} → {type(actual).__name__}"]

    if isinstance(base, dict):
        for k in base.keys() - actual.keys():
            difs.append(f"{ruta}.{k}: desapareció (valía {base[k]!r})")
        for k in actual.keys() - base.keys():
            difs.append(f"{ruta}.{k}: apareció (vale {actual[k]!r})")
        for k in base.keys() & actual.keys():
            difs += comparar(base[k], actual[k], f"{ruta}.{k}")
        return difs

    if isinstance(base, list):
        b, a = _ordenable(base), _ordenable(actual)
        if len(b) != len(a):
            difs.append(f"{ruta}: la lista pasó de {len(b)} a {len(a)} elementos")
        for i, (eb, ea) in enumerate(zip(b, a)):
            difs += comparar(eb, ea, f"{ruta}[{i}]")
        return difs

    if base != actual:
        difs.append(f"{ruta}: {base!r} → {actual!r}")
    return difs


def plantas(payload) -> list[dict]:
    """Todos los nodos de planta del árbol, sin depender de cómo esté anidado.

    Una planta es cualquier dict con un `detalles` que también es dict. Se busca
    recursivamente a propósito: si la Fase 4 cambia el anidamiento, eso lo tiene
    que cazar `comparar()`, no romper los invariantes por un KeyError.
    """
    encontradas: list[dict] = []

    def caminar(nodo):
        if isinstance(nodo, dict):
            if isinstance(nodo.get("detalles"), dict):
                encontradas.append(nodo)
            for v in nodo.values():
                caminar(v)
        elif isinstance(nodo, list):
            for v in nodo:
                caminar(v)

    caminar(payload)
    return encontradas


def revisar_invariantes(payload) -> list[str]:
    """Los tres invariantes que la Fase 4 no puede romper (`05` §4).

    Devuelve la lista de violaciones. Vacía = todo bien.
    """
    fallas: list[str] = []

    for i, planta in enumerate(plantas(payload)):
        d = planta.get("detalles", {})
        etiqueta = planta.get("nombre") or planta.get("id") or f"planta[{i}]"

        # 1 · `operador_red_id` en null es SEÑAL de "no está en el catálogo", no
        #     un hueco a rellenar. El campo tiene que existir siempre, aunque
        #     valga null: si desaparece, el consumidor no puede distinguir
        #     "no está en el catálogo" de "no me lo mandaron".
        if "operador_red_id" not in d:
            fallas.append(f"{etiqueta}: falta la clave `operador_red_id` en detalles")

        # 2 · Las series de simulación conservan su longitud real, y
        #     `p50_anual_kwh` es null si no hay 12 meses. Sumar 7 y llamarlo
        #     anual sería mentira.
        sim = d.get("simulacion")
        if isinstance(sim, dict):
            p50 = sim.get("p50_mensual_kwh")
            anual = sim.get("p50_anual_kwh")
            if p50 is not None and len(p50) != 12 and anual is not None:
                fallas.append(
                    f"{etiqueta}: p50_anual_kwh={anual} con una serie de "
                    f"{len(p50)} meses; debe ser null si no son 12")
            if p50 is None and anual is not None:
                fallas.append(f"{etiqueta}: p50_anual_kwh={anual} sin serie p50")

        # 3 · `energia_promedio_detalle` sale con los 4 campos en null cuando el
        #     origen es estimado o declarado: no hubo medición que describir.
        origen = d.get("energia_promedio_origen")
        detalle = d.get("energia_promedio_detalle")
        if origen in ORIGENES_SIN_DETALLE and isinstance(detalle, dict):
            con_valor = [c for c in CAMPOS_DETALLE if detalle.get(c) is not None]
            if con_valor:
                fallas.append(
                    f"{etiqueta}: origen={origen} pero energia_promedio_detalle "
                    f"trae {con_valor}; los 4 campos deben ser null")
        if origen in ORIGENES_SIN_DETALLE and detalle is None:
            fallas.append(
                f"{etiqueta}: origen={origen} y `energia_promedio_detalle` "
                f"desapareció; tiene que estar, con los 4 campos en null")

    return fallas
