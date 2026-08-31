"""Estado compartido de anti-spam para alarmas (tabla alarma_estado) y envío
de notificaciones in-app -- usado por desconexion.py (poll cada 15 min,
muchos proyectos a la vez) y por fallas/alarmas.py (reactivo, un proyecto
por evento). Centralizado para que las dos fuentes de alarmas compartan la
misma lógica de "cuándo notificar" y no diverjan con el tiempo (auditoría
2026-08-31: fallas/alarmas.py nunca escribía el estado 'ok' de vuelta
cuando una alarma de comunicación se resolvía, así que un segundo
incidente real el mismo día quedaba sin avisar -- desconexion.py sí lo
hacía bien, de ahí la unificación en este módulo)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from app.models.usuarios import Usuario, RolEnum
from app.models.notificaciones import Notificacion, TipoNotificacionEnum

ROLES_NOTIF = (RolEnum.admin, RolEnum.operaciones, RolEnum.monitoreo)


def cargar_estados(db, proyecto_ids: list[int]) -> dict[tuple[int, str], tuple[str, date | None]]:
    """Precarga alarma_estado para los proyectos dados -- un solo SELECT en
    vez de uno por (proyecto, categoria) dentro de decidir_notificar()."""
    if not proyecto_ids:
        return {}
    rows = db.execute(
        text("SELECT proyecto_id, categoria, estado, dia FROM alarma_estado "
             "WHERE proyecto_id = ANY(:ids)"),
        {"ids": list(proyecto_ids)},
    ).fetchall()
    return {(r.proyecto_id, r.categoria): (r.estado, r.dia) for r in rows}


def decidir_notificar(
    cache: dict[tuple[int, str], tuple[str, date | None]],
    pending_writes: list[dict],
    proyecto_id: int, categoria: str, estado_nuevo: str, hoy: date,
) -> tuple[bool, bool]:
    """Compara `estado_nuevo` con lo cacheado y decide si toca notificar --
    cambio de estado, o persiste y no se avisó hoy (re-aviso diario). Si
    toca, encola la escritura en `pending_writes` (ver guardar_estados) y
    actualiza `cache` in-place para que llamadas subsiguientes en la misma
    corrida vean el cambio. Devuelve (notify, recovery) -- recovery=True
    cuando el estado nuevo es 'ok' y el anterior no lo era."""
    row = cache.get((proyecto_id, categoria))
    notify = False
    recovery = False
    if row is None:
        notify = estado_nuevo != "ok"
    elif row[0] != estado_nuevo:
        notify = True
        recovery = estado_nuevo == "ok"
    elif estado_nuevo != "ok" and (row[1] is None or row[1] < hoy):
        notify = True  # re-aviso diario mientras persista

    if notify:
        dia_val = hoy if estado_nuevo != "ok" else None
        pending_writes.append({"p": proyecto_id, "c": categoria, "e": estado_nuevo, "d": dia_val})
        cache[(proyecto_id, categoria)] = (estado_nuevo, dia_val)
    return notify, recovery


def guardar_estados(db, pending_writes: list[dict]) -> None:
    """UPSERT masivo de todas las filas que cambiaron -- una sola sentencia
    con VALUES múltiples en vez de un INSERT/UPDATE por fila."""
    if not pending_writes:
        return
    valores = ", ".join(f"(:p{i}, :c{i}, :e{i}, :d{i}, now())" for i in range(len(pending_writes)))
    params: dict = {}
    for i, w in enumerate(pending_writes):
        params[f"p{i}"] = w["p"]
        params[f"c{i}"] = w["c"]
        params[f"e{i}"] = w["e"]
        params[f"d{i}"] = w["d"]
    db.execute(text(f"""
        INSERT INTO alarma_estado (proyecto_id, categoria, estado, dia, updated_at)
        VALUES {valores}
        ON CONFLICT (proyecto_id, categoria)
        DO UPDATE SET estado = EXCLUDED.estado, dia = EXCLUDED.dia, updated_at = now()
    """), params)


def usuarios_notificables(db) -> list[Usuario]:
    """Usuarios activos con rol operativo (admin/operaciones/monitoreo) --
    destinatarios de toda alarma in-app. Pedirlo una sola vez por corrida,
    no una vez por categoría/proyecto que notifica."""
    return db.query(Usuario).filter(
        Usuario.activo == True,  # noqa: E712
        Usuario.rol.in_(list(ROLES_NOTIF)),
    ).all()


def notificar(db, usuarios: list[Usuario], tipo: TipoNotificacionEnum,
              titulo: str, mensaje: str) -> None:
    for u in usuarios:
        db.add(Notificacion(usuario_id=u.id, tipo=tipo, titulo=titulo, mensaje=mensaje))
