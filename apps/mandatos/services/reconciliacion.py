"""Reconciliación por conteo: qué se envió contra qué volvió.

Puro -- recibe filas ya cargadas y devuelve el balance. Sin BD, sin red.

Responde la pregunta que hoy solo contesta el script local de Jessica: "envié 32
mandatos de julio, ¿volvieron los 32?". Poder responderla en la plataforma es la
condición que ella puso para dejar de correr su script.
"""
from __future__ import annotations

# Estados que significan "la revisoría ya se pronunció sobre este mandato".
# con_comentarios cuenta como devuelto: volvió, aunque con trabajo pendiente.
_DEVUELTOS = {"firmado", "con_comentarios", "corregido", "enviado_inversionista"}


def reconciliar(filas) -> dict:
    """Balance de un período. `filas` son registros con cmu, estado y fecha_envio.

    - enviados: los que constan como enviados a la revisoría
    - devueltos: los que ya volvieron, en cualquier forma
    - pendientes: enviados que no han vuelto -- la lista que importa
    - con_comentarios: volvieron pero hay que corregirlos
    - sin_registro_de_envio: aparecieron sin constar como enviados. Anomalía:
      o se envió por fuera del canal, o el correo de salida no se leyó. Se
      reporta aparte para no inflar el denominador y esconder el problema.
    """
    enviados, devueltos = [], []
    con_comentarios, sin_envio = [], []

    for f in filas:
        if not getattr(f, "fecha_envio", None):
            sin_envio.append(f.cmu)
            continue
        enviados.append(f.cmu)
        if f.estado in _DEVUELTOS:
            devueltos.append(f.cmu)
        if f.estado == "con_comentarios":
            con_comentarios.append(f.cmu)

    pendientes = [c for c in enviados if c not in set(devueltos)]
    return {
        "enviados": len(enviados),
        "devueltos": len(devueltos),
        "pendientes": pendientes,
        "con_comentarios": con_comentarios,
        "sin_registro_de_envio": sin_envio,
        "completo": not pendientes,
    }
