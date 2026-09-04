"""Anti-spam de alarmas (tabla `alarma_estado`) y envío de notificaciones in-app.

Puerto de `app/services/alarmas/estado.py`. Lo comparten las alarmas de
desconexión (poll cada 15 min, muchos proyectos a la vez) y las de comunicación
derivadas de fallas (reactivas, un proyecto por evento).

Está centralizado para que las dos fuentes no diverjan: hasta el 2026-08-31 las
alarmas de fallas nunca escribían el estado `ok` de vuelta al resolverse, así que
un segundo incidente real el mismo día quedaba sin avisar — las de desconexión sí
lo hacían bien, de ahí la unificación.

`alarma_estado` es una de las 28 tablas sin modelo (ver apps/README.md): de ahí el
SQL crudo.
"""

from __future__ import annotations

from datetime import date

from django.db import connection

from apps.plataforma.models import Notificacion, Usuario

ROLES_NOTIF = ("admin", "operaciones", "monitoreo")


def cargar_estados(proyecto_ids: list[int]) -> dict[tuple[int, str], tuple[str, date | None]]:
    """Precarga `alarma_estado` para esos proyectos — un solo SELECT en vez de
    uno por (proyecto, categoría) dentro de `decidir_notificar`."""
    if not proyecto_ids:
        return {}
    with connection.cursor() as cur:
        cur.execute(
            "SELECT proyecto_id, categoria, estado, dia FROM alarma_estado "
            "WHERE proyecto_id = ANY(%s)",
            [list(proyecto_ids)],
        )
        return {(p, c): (e, d) for p, c, e, d in cur.fetchall()}


def decidir_notificar(cache, pending_writes: list[dict], proyecto_id: int,
                      categoria: str, estado_nuevo: str, hoy: date) -> tuple[bool, bool]:
    """`(notificar, es_recuperacion)`.

    Toca notificar si el estado cambió, o si persiste y no se avisó hoy
    (re-aviso diario). Encola la escritura en `pending_writes` y actualiza
    `cache` in situ, para que las llamadas siguientes de la misma corrida vean
    el cambio.
    """
    fila = cache.get((proyecto_id, categoria))
    notificar_ = recuperacion = False
    if fila is None:
        notificar_ = estado_nuevo != "ok"
    elif fila[0] != estado_nuevo:
        notificar_ = True
        recuperacion = estado_nuevo == "ok"
    elif estado_nuevo != "ok" and (fila[1] is None or fila[1] < hoy):
        notificar_ = True  # re-aviso diario mientras persista

    if notificar_:
        dia = hoy if estado_nuevo != "ok" else None
        pending_writes.append({
            "p": proyecto_id, "c": categoria, "e": estado_nuevo, "d": dia,
        })
        cache[(proyecto_id, categoria)] = (estado_nuevo, dia)
    return notificar_, recuperacion


def guardar_estados(pending_writes: list[dict]) -> None:
    """UPSERT masivo de las filas que cambiaron: una sola sentencia."""
    if not pending_writes:
        return
    valores = ", ".join(["(%s, %s, %s, %s, now())"] * len(pending_writes))
    params: list = []
    for w in pending_writes:
        params += [w["p"], w["c"], w["e"], w["d"]]
    with connection.cursor() as cur:
        cur.execute(
            f"INSERT INTO alarma_estado (proyecto_id, categoria, estado, dia, updated_at) "
            f"VALUES {valores} "
            f"ON CONFLICT (proyecto_id, categoria) "
            f"DO UPDATE SET estado = EXCLUDED.estado, dia = EXCLUDED.dia, "
            f"updated_at = now()",
            params,
        )


def usuarios_notificables() -> list[Usuario]:
    """Los destinatarios de toda alarma in-app. Se piden UNA vez por corrida, no
    una por categoría y proyecto que notifica."""
    return list(Usuario.objects.filter(activo=True, rol__in=ROLES_NOTIF))


def notificar(usuarios: list[Usuario], tipo: str, titulo: str, mensaje: str) -> None:
    Notificacion.objects.bulk_create([
        Notificacion(usuario_id=u.id, tipo=tipo, titulo=titulo, mensaje=mensaje, leida=False)
        for u in usuarios
    ])
