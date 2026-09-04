"""Proyectos próximos a energizarse — leído de la BD de operaciones.

Puerto de `app/api/v1/proximos_energizar.py`. El pipeline de TSF ya NO se lee en
vivo acá: un job lo sincroniza hacia `proyectos` (ver `tsf_sync.py`). Todos los
campos son de solo lectura: vienen tal cual de Sun Factory/TSF, sin edición
manual del operador.

**No se portó `_ensure_tsf_columns`.** El original emitía seis
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en el primer request de cada proceso,
"por si la migración no corrió". Es exactamente el patrón `_PENDING_DDLS` que se
retiró del repo el 2026-08-31 (CLAUDE.md): DDL sin control de versión, en el
camino caliente y con el error tragado. Hoy el esquema lo posee Alembic y
`scripts/verificar_esquema.py` tumba el deploy si a la base le falta una columna
declarada — que es justo lo que ese bloque intentaba tapar.
"""

from __future__ import annotations

import logging

from django.db.models import F, Max, Q

from apps.fronteras.models import Frontera
from apps.plataforma.services.fechas import hoy_col
from apps.proyectos.models import Proyecto
from apps.proyectos.services.tsf_sync import _FASE_TO_LABEL

logger = logging.getLogger("operaciones.proximos_energizar")


def _serialize(p: Proyecto, contratos: list[str], frontera: dict | None = None) -> dict:
    """Forma que consume `ProyectosProximosEnergizar.vue`."""
    fase = p.fase_construccion
    status = _FASE_TO_LABEL.get(fase) if fase else None
    return {
        "id": p.id,
        "name": p.origina_code or p.codigo_tsf or "",
        "commercialName": p.nombre_comercial,
        "status": status or "En construcción",
        "energizationDate": p.fecha_estimada_energizacion.isoformat() if p.fecha_estimada_energizacion else None,
        "avancePct": float(p.avance_obra_pct) if p.avance_obra_pct is not None else None,
        # `mwh_mes_estimado` se retiró el 2026-08-20 (0/194 proyectos lo tuvieron
        # alguna vez, sin ningún formulario que lo escribiera): `monthlyMwh` queda
        # fijo en 0 hasta que exista una fuente real que lo llene.
        "monthlyMwh": 0,
        "contracts": contratos,
        "municipio": p.municipio,
        "departamento": p.departamento,
        "origen": p.origen,
        # "Frontera asignada": qué proyectos en construcción ya tienen frontera
        # comercial registrada — señal de energización inminente más confiable que
        # la fase de Sun Factory. Sale de nuestra tabla `fronteras`, no de una
        # llamada en vivo a Quoia.
        "tieneFrontera": frontera is not None,
        "codigoFrontera": frontera["codigo_frontera"] if frontera else None,
    }


def _fronteras_por_proyecto(proyecto_ids: list[int]) -> dict[int, dict]:
    """`{proyecto_id: {codigo_frontera}}` de la frontera de generación de cada
    proyecto (si tiene varias, la primera). Une `generacion` y
    `generacion_consumo`: las dos son puntos de generación real."""
    if not proyecto_ids:
        return {}
    salida: dict[int, dict] = {}
    filas = (
        Frontera.objects
        .filter(
            proyecto_id__in=proyecto_ids,
            tipo_frontera__in=["generacion", "generacion_consumo"],
            deleted_at__isnull=True,
        )
        .values_list("proyecto_id", "codigo_frontera")
    )
    for proyecto_id, codigo in filas:
        salida.setdefault(proyecto_id, {"codigo_frontera": codigo})
    return salida


def _contratos_por_proyecto(proyecto_ids: list[int]) -> dict[int, list[str]]:
    """Una consulta para los contratos de todos los proyectos, no una por fila."""
    from apps.ppa.models import PpaContratoProyecto

    salida: dict[int, list[str]] = {}
    filas = (
        PpaContratoProyecto.objects
        .filter(proyecto_id__in=proyecto_ids)
        .select_related("contrato")
        .values_list(
            "proyecto_id", "contrato__nombre_interno",
            "contrato__numero_codigo_contrato",
        )
    )
    for proyecto_id, interno, codigo in filas:
        etiqueta = interno or codigo
        if etiqueta:
            salida.setdefault(proyecto_id, []).append(etiqueta)
    return salida


def _generando_ya(proyectos, fronteras: dict[int, dict]) -> set[int]:
    """Los que ya generan de verdad según Quoia, aunque nadie lo haya confirmado.

    NO toca `estado` ni `fase_construccion` en la base: esa confirmación sigue
    siendo manual. Esto solo evita que la vista dependa de que alguien revise
    Pendientes a tiempo. Cacheado 1 h, así que casi nunca golpea Quoia.

    `ponytail: el cruce con Quoia sigue en app/services/proyectos_pendientes.py`.
    Son 546 líneas sin sesión de base (solo HTTP contra Gaia) que se portan con
    `/proyectos`, su dueño; traerlas acá por tres endpoints sería moverlas dos
    veces.
    """
    ids_con_frontera = [p.id for p in proyectos if p.id in fronteras]
    if not ids_con_frontera:
        return set()
    try:
        from app.services.mgs.gaia_client import GaiaClient
        from app.services.proyectos_pendientes import _generacion_real_por_frt

        gaia = GaiaClient()
        if not gaia.enabled:
            return set()
        generacion_real = _generacion_real_por_frt(gaia, gaia.get_all_borders())
        return {
            pid for pid in ids_con_frontera
            if generacion_real.get((fronteras[pid]["codigo_frontera"] or "").strip().lower())
        }
    except Exception as exc:
        logger.warning(
            "Verificación de generación real falló (se ignora, no bloquea la vista): %s", exc
        )
        return set()


def listar() -> dict:
    """Proyectos del pipeline TSF en fase activa + registrados cuya fecha de
    energización aún no llega. Todo leído de la BD de operaciones."""
    today = hoy_col()
    try:
        filas = list(
            Proyecto.objects
            .filter(deleted_at__isnull=True)
            # Si YA está marcado como en operación —por confirmación manual o por
            # evidencia de Quoia/Solenium en /proyectos/pendientes— no debe seguir
            # apareciendo acá, aunque Sun Factory siga diciendo "en construcción".
            .exclude(estado="en_operacion")
            .filter(
                (Q(fase_construccion__isnull=False) & ~Q(fase_construccion="energizado"))
                | Q(fecha_estimada_energizacion__gt=today)
            )
            # NULLS LAST: los que aún no tienen fecha van al final, no al principio.
            .order_by(F("fecha_estimada_energizacion").asc(nulls_last=True))
        )
    except Exception as exc:
        # Nunca tumbar la vista por un problema de esquema o consulta: degradar.
        logger.warning("listar_proximos_energizar falló: %s", exc)
        return {
            "projects": [], "source": "error", "count": 0,
            "warning": "No se pudo cargar la lista. Intenta «Sincronizar ahora» "
                       "para poblar el pipeline desde Solenium/TSF.",
        }

    fronteras = _fronteras_por_proyecto([p.id for p in filas])
    filas = [p for p in filas if p.id not in _generando_ya(filas, fronteras)]
    contratos = _contratos_por_proyecto([p.id for p in filas])

    # Última vez que el sync (on-demand o el job de 6 h) tocó CUALQUIER proyecto
    # vinculado a Sun Factory: no depende de que el usuario haya apretado
    # "Actualizar" en su sesión, así que es correcto en la primera carga.
    ultima_sync = (
        Proyecto.objects
        .filter(sunfactory_project_id__isnull=False, deleted_at__isnull=True)
        .aggregate(ultima=Max("updated_at"))["ultima"]
    )

    return {
        "projects": [
            _serialize(p, contratos.get(p.id, []), fronteras.get(p.id)) for p in filas
        ],
        "source": "operaciones_db",
        "count": len(filas),
        "ultimaSincronizacion": ultima_sync.isoformat() if ultima_sync else None,
    }
