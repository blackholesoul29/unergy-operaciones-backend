"""Resolución de VIGENCIA EFECTIVA de solicitudes GESCON/ASIC.

Problema que resuelve
─────────────────────
`asic_solicitudes` guarda cada solicitud histórica como fila permanente
(registro + modificaciones). Cuando una modificación posterior releva a una
planta en un SIC (reemplaza_anterior=True con proyecto distinto) o supersede
en sitio a la misma planta, la fila vieja conserva su `fecha_fin` cruda
(p. ej. 2039) aunque su vigencia REAL terminó el día anterior al relevo.
Cualquier consumidor que compare ventanas con la `fecha_fin` cruda (validación
de solapamiento en GESCON, alertas de duplicados) produce falsos positivos:
una planta reubicada de un contrato a otro parece "activa en dos contratos a
la vez" (caso real: SIC 89116, MGS 0012 La Reserva).

Este módulo generaliza el walk por SIC de `_resolve_gescon`
(app/api/v1/cumplimiento.py) — la implementación canónica y testeada — a una
función pura SIN acoplamiento a un mes: para cada fila devuelve su ventana
efectiva y si es la versión vigente. `_resolve_gescon` se apoya en este mismo
núcleo (parámetro `hasta`) para reconstruir la vista histórica de un mes.

Reglas (idénticas a _resolve_gescon):
- Los eventos se procesan cronológicamente por `fecha_inicio` (cuándo tomó
  efecto, no cuándo se radicó). `fecha_inicio` NULL = vigente desde siempre.
- Modificación de la MISMA planta en el mismo SIC → supersede en sitio: la
  versión anterior queda recortada a `fecha_inicio − 1` y deja de ser vigente.
- Registro/modificación de una planta DISTINTA con reemplaza_anterior=True →
  relevo: TODAS las plantas activas del SIC quedan recortadas a
  `fecha_inicio − 1` (`saliente_por_relevo=True`, ver docstring de
  _resolve_gescon: el prorrateo por días necesita distinguirlas).
- reemplaza_anterior=False → coexiste con las plantas activas (no recorta).
- Terminación → cierra el SIC en su `fecha_fin`: TODAS las plantas activas
  quedan recortadas a esa fecha. Toma efecto en `fecha_fin` (una terminación
  no "empieza" nada: cierra ese día), no en `fecha_inicio`, que va nula.

  Antes esto no se resolvía aquí: se confiaba en que `_auto_terminate` ya
  había estampado la fecha en los registros al guardar la terminación. Pero
  eso se materializa UNA vez, al escribir la terminación, y se desincroniza
  solo — una terminación cargada directo a la BD nunca lo corrió, y un
  registro creado o editado DESPUÉS con una fecha posterior no lo vuelve a
  correr. Cuando eso pasa la terminación se vuelve invisible para todos los
  consumidores a la vez y la planta sigue apareciendo en su contrato (caso
  real: MGS 0008 La Paz Verso, terminación 202608130012, que seguía contando
  duplicada). Derivarlo aquí lo hace robusto: el recorte no puede perderse
  porque no se guarda en ninguna parte.

El llamador debe pasar SOLO solicitudes publicadas, sin desistimientos (mismo
filtro que _resolve_gescon). Filas en otros estados no participan de la
resolución: el llamador decide qué reportar para ellas.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class Vigencia:
    """Resultado de la resolución para UNA fila de asic_solicitudes."""

    fecha_fin_efectiva: date | None  # fin real de la ventana; None = abierta
    vigente: bool                    # es la versión vigente actual de su SIC
    # Ya no es la versión vigente, pero su ventana recortada SÍ cuenta: el
    # consumidor debe incluirla prorrateada hasta `fecha_fin_efectiva` en vez de
    # descartarla. Pasa cuando releva otra planta y cuando la cierra una
    # terminación. (Una versión superada EN SITIO por su propia planta no lleva
    # esta marca: la representa su versión nueva.)
    saliente_por_relevo: bool
    reemplazado_por_id: int | None   # id de la solicitud que la desplazó
    procesado: bool                  # tomó efecto dentro del horizonte `hasta`


def _tipo(r) -> str:
    """tipo_solicitud tolerante a Enum ORM o string plano."""
    t = getattr(r, "tipo_solicitud", None)
    return getattr(t, "value", t)


def _vigente_desde(r) -> date:
    """Día en que el evento toma efecto.

    Para una terminación es su `fecha_fin`: no empieza nada, cierra el contrato
    ese día — y además le va `fecha_inicio` nula, así que ordenarla por inicio
    la mandaría al principio de la fila, antes de que exista nada que cerrar.
    """
    if _tipo(r) == "terminacion":
        return r.fecha_fin or date.min
    return r.fecha_inicio or date.min


def _orden(r):
    """Clave de orden cronológico. En empate de fecha la terminación va de
    última: si un registro arranca el mismo día que cierra el contrato, primero
    entra y después se cierra. Empates restantes: el sort estable conserva el
    orden de entrada (los llamadores ya ordenan por created_at en la query)."""
    return (
        _vigente_desde(r),
        1 if _tipo(r) == "terminacion" else 0,
        r.fecha_solicitud or date.min,
    )


def _dia_anterior(d: date) -> date:
    """d − 1 día, sin desbordar cuando fecha_inicio es NULL (date.min)."""
    return d - timedelta(days=1) if d > date.min else date.min


def resolver_vigencias(records, hasta: date | None = None) -> dict[int, Vigencia]:
    """Devuelve {id_solicitud: Vigencia} para TODAS las filas dadas.

    records: solicitudes ya filtradas (publicadas, sin desistimientos). Las
             terminaciones sí entran: ejecutan su efecto y quedan vigente=False.
    hasta:   horizonte de eventos. Los que toman efecto después
             (fecha_inicio > hasta) no se procesan (procesado=False) ni
             desplazan a nadie — reproduce la vista histórica por mes de
             _resolve_gescon. None = procesar todo (estado actual).
    """
    by_sic: dict[str, list] = defaultdict(list)
    for r in records:
        by_sic[r.codigo_sic_contrato or f"_id_{r.id}"].append(r)

    out: dict[int, Vigencia] = {}
    for sic_records in by_sic.values():
        active: dict[int | str, object] = {}
        for r in sorted(sic_records, key=_orden):
            vigente_desde = _vigente_desde(r)
            if hasta is not None and vigente_desde > hasta:
                out[r.id] = Vigencia(r.fecha_fin, False, False, None, procesado=False)
                continue

            pid = r.proyecto_id
            if _tipo(r) == "terminacion":
                out[r.id] = Vigencia(r.fecha_fin, False, False, None, True)
                if r.fecha_fin is None:
                    continue  # sin fecha no cierra nada
                # Cierra el SIC: las plantas activas quedan recortadas al día de
                # la terminación. Se marcan salientes (no simplemente "no
                # vigentes") para que el consumidor las prorratee hasta esa
                # fecha en vez de borrarlas del mes.
                # Las terminaciones viejas llevan proyecto_id (hoy va nulo a
                # propósito): en ese caso solo se cierra esa planta.
                objetivos = (
                    [(pid, active[pid])] if pid is not None and pid in active
                    else [] if pid is not None
                    else list(active.items())
                )
                for clave, saliente in objetivos:
                    fin_ef = min(saliente.fecha_fin or date.max, r.fecha_fin)
                    out[saliente.id] = Vigencia(fin_ef, False, True, r.id, True)
                    active.pop(clave, None)
                continue

            if pid is None:
                # Sin planta: entrada propia, coexiste bajo llave sintética
                active[f"_nopid_{r.id}"] = r
                out[r.id] = Vigencia(r.fecha_fin, True, False, None, True)
                continue

            if pid in active:
                # Supersesión en sitio (misma planta): la versión previa queda
                # recortada al día anterior a que la nueva tome efecto.
                prev = active[pid]
                corte = _dia_anterior(vigente_desde)
                fin_prev = min(prev.fecha_fin or date.max, corte)
                out[prev.id] = Vigencia(fin_prev, False, False, r.id, True)
                active[pid] = r
                out[r.id] = Vigencia(r.fecha_fin, True, False, None, True)
                continue

            if r.reemplaza_anterior:
                # Relevo: la nueva planta desplaza a TODAS las activas del SIC.
                corte = _dia_anterior(vigente_desde)
                for saliente in active.values():
                    fin_ef = min(saliente.fecha_fin or date.max, corte)
                    out[saliente.id] = Vigencia(fin_ef, False, True, r.id, True)
                active.clear()
            active[pid] = r
            out[r.id] = Vigencia(r.fecha_fin, True, False, None, True)

    return out
