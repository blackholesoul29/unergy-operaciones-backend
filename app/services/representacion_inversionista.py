"""Vincula el contrato de representacion con el inversionista de la planta.

El problema que resuelve: `contratos_servicio.inversionista_nombre` es texto
libre, mientras la participacion real vive en `proyecto_inversionistas`
(`cliente_id` + `fecha_inicio`/`fecha_fin`). Sin un puente entre los dos, la
tabla de Representacion muestra "Vigente" un contrato cuyo inversionista salio de
la planta hace meses -- MGS 0024 San Diego Sur salia con tres contratos vigentes
cuando solo uno de los tres inversionistas seguia participando.

El puente es `contratos_servicio.inversionista_id`. Este modulo hace dos cosas:

1. **Emparejar** (`emparejar`): propone el `cliente_id` para los contratos que
   todavia no lo tienen, comparando el nombre normalizado contra los
   inversionistas de ESA planta. Solo dentro de la planta: comparar contra todos
   los clientes de la base es lo que cuelga registros donde no van.

2. **Cerrar** (`cierres_pendientes`): dice que contratos hay que dar por
   terminados porque la participacion de su inversionista ya acabo.

Ninguna de las dos escribe: devuelven lo que habria que hacer, y quien llama
decide. Asi se pueden probar sin base de datos y auditar antes de aplicar.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Iterable, NamedTuple


def norm(s: Any) -> str:
    """Normaliza para comparar: solo letras y digitos, en mayusculas.

    Mismo criterio que `representacion_dedup.norm`: "Ayura S.A.S." y
    "AYURA SAS" tienen que ser el mismo inversionista.
    """
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _valor(obj: Any, campo: str) -> Any:
    return obj.get(campo) if isinstance(obj, dict) else getattr(obj, campo, None)


class Pareja(NamedTuple):
    contrato_id: int
    cliente_id: int
    # Por que se emparejo, para poder auditar el backfill.
    criterio: str
    nombre_contrato: str
    nombre_cliente: str


def _candidatos(participaciones: Iterable[Any]) -> list[tuple[str, Any]]:
    """(nombre normalizado del cliente, participacion) para una planta."""
    salida = []
    for p in participaciones:
        nombre = _valor(p, "cliente_nombre")
        if not nombre:
            cliente = _valor(p, "cliente")
            nombre = _valor(cliente, "razon_social_nombre") if cliente else None
        if nombre:
            salida.append((norm(nombre), p))
    return salida


def emparejar(contrato: Any, participaciones: Iterable[Any]) -> Pareja | None:
    """Propone el inversionista de un contrato entre los de su misma planta.

    Dos criterios, en orden, y ambos exigen que el resultado sea UNICO:

    1. Nombre normalizado igual.
    2. El nombre del contrato es prefijo del nombre del cliente. Es el caso de
       los patrimonios autonomos: el contrato dice "PATRIMONIOS AUTONOMOS
       FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA" y el cliente de la planta
       agrega el fideicomiso concreto ("… - 17844 SOL DE LA SIERRA"). Se acepta
       solo si un unico cliente empieza asi; con dos fideicomisos de la misma
       fiduciaria en la planta no hay forma de saber cual es y no se adivina.

    Se compara solo contra los inversionistas de ESA planta, no contra todos los
    clientes: es la misma leccion del matcher de proyectos, donde buscar en todo
    el universo colgaba contratos donde no correspondian.
    """
    nombre = _valor(contrato, "inversionista_nombre")
    objetivo = norm(nombre)
    if not objetivo:
        return None

    cands = _candidatos(participaciones)
    if not cands:
        return None

    cid = _valor(contrato, "id")

    exactos = {_valor(p, "cliente_id") for n, p in cands if n == objetivo}
    if len(exactos) == 1:
        cliente_id = exactos.pop()
        nombre_cliente = next(_valor(p, "cliente_nombre") for n, p in cands
                              if _valor(p, "cliente_id") == cliente_id)
        return Pareja(cid, cliente_id, "nombre exacto", nombre or "", nombre_cliente or "")

    # Prefijo: el cliente de la planta amplia el nombre del contrato.
    prefijos = {_valor(p, "cliente_id") for n, p in cands
                if n.startswith(objetivo) and n != objetivo}
    if len(prefijos) == 1:
        cliente_id = prefijos.pop()
        nombre_cliente = next(_valor(p, "cliente_nombre") for n, p in cands
                              if _valor(p, "cliente_id") == cliente_id)
        return Pareja(cid, cliente_id, "prefijo del nombre", nombre or "",
                      nombre_cliente or "")

    return None


class Cierre(NamedTuple):
    contrato_id: int
    fecha_fin: date
    # Se rellena `fecha_fin` solo si el contrato no traia una propia.
    poner_fecha: bool
    motivo: str


def _participaciones_de(cliente_id: int, participaciones: Iterable[Any]) -> list[Any]:
    return [p for p in participaciones if _valor(p, "cliente_id") == cliente_id]


def cierre_de(contrato: Any, participaciones: Iterable[Any],
              hoy: date) -> Cierre | None:
    """Devuelve el cierre que corresponde a un contrato, o None si sigue vigente.

    Se cierra cuando TODAS las participaciones de ese inversionista en la planta
    terminaron antes de hoy. Si tiene aunque sea un periodo abierto (`fecha_fin`
    NULL) o futuro, el contrato sigue: un inversionista puede salir y volver, y
    entonces el contrato no debe cerrarse.
    """
    cliente_id = _valor(contrato, "inversionista_id")
    if cliente_id is None:
        return None                      # sin vincular: no se puede afirmar nada
    if _valor(contrato, "estado") == "terminado":
        return None                      # ya esta cerrado

    suyas = _participaciones_de(cliente_id, participaciones)
    if not suyas:
        # Vinculado a un cliente que no figura como inversionista de la planta.
        # Es un dato incoherente, no un contrato terminado: no se toca.
        return None

    fines = [_valor(p, "fecha_fin") for p in suyas]
    if any(f is None or f >= hoy for f in fines):
        return None                      # hay un periodo abierto o vigente

    ultima = max(f for f in fines)
    return Cierre(
        contrato_id=_valor(contrato, "id"),
        fecha_fin=ultima,
        poner_fecha=_valor(contrato, "fecha_fin") is None,
        motivo=f"la participacion del inversionista termino el {ultima.isoformat()}",
    )


def cierres_pendientes(contratos: Iterable[Any], participaciones_por_proyecto: dict,
                       hoy: date) -> list[Cierre]:
    """Cierres que tocan, mirando cada contrato contra los inversionistas de su
    propia planta."""
    salida = []
    for c in contratos:
        pid = _valor(c, "proyecto_id")
        if pid is None:
            continue
        cierre = cierre_de(c, participaciones_por_proyecto.get(pid, []), hoy)
        if cierre:
            salida.append(cierre)
    return salida
