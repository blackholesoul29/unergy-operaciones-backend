"""Título legible de una falla para consumidores que no entienden `clasificacion`
(correo de notificación, API pública externa) -- espejo en Python de
`tituloFalla()` en el frontend (app/features/fallas/utils/fallaTitulo.ts).

Reemplaza el uso de `tipo_libre` (eliminado -- auditoría 2026-09-02): para
fallas estructuradas el título se arma al vuelo desde `clasificacion`, en vez
de leer un valor guardado que había que mantener sincronizado con un backfill
permanente. Para fallas legacy sin `clasificacion`, cae a `tipo.etiqueta`.
"""
from app.models.fallas import Falla


def titulo_falla(falla: "Falla") -> str:
    c = falla.clasificacion
    if isinstance(c, dict) and c.get("categoria"):
        inversores = c.get("inversores")
        if inversores:
            nombres = ", ".join(
                inv.get("nombre") or f"Inversor {inv.get('proyecto_inversor_id')}"
                for inv in inversores
            )
            tipos = ", ".join(sorted({
                t for inv in inversores for t in (inv.get("tipos_etiquetas") or [])
            }))
            return f"{nombres} — {tipos}" if tipos else nombres
        if c.get("subtipo_etiqueta"):
            return f"{c['subtipo_etiqueta']}: {c['detalle']}" if c.get("detalle") else c["subtipo_etiqueta"]
        if c.get("categoria_etiqueta"):
            return c["categoria_etiqueta"]
    return falla.tipo.etiqueta if falla.tipo else "Sin tipo"
