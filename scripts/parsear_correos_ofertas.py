"""Lee los .eml exportados por Alejandro y emite el bloque `envios[]` del
archivo de actualizacion del CRM comercial.

Uso (Windows):
    set PYTHONIOENCODING=utf-8
    python scripts/parsear_correos_ofertas.py "C:\\...\\Ofertas\\Correos" envios_2026-07.json

No toca la base de datos: su salida se revisa a mano y se pega en
data/comercial_actualizacion_2026-07.json.
"""
import email
import glob
import html as H
import json
import os
import re
import sys
from email import policy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.correos_hilo import codigo_partes, datos_envio, hilo_completo  # noqa: E402

_RE_CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def cuerpo_texto(msg) -> str:
    """text/plain si existe; si no, el html desnudado de etiquetas."""
    p = msg.get_body(preferencelist=("plain",))
    if p:
        return p.get_content()
    p = msg.get_body(preferencelist=("html",))
    if not p:
        return ""
    h = p.get_content()
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h, flags=re.I)
    return re.sub(r"[ \t]{2,}", " ", H.unescape(re.sub(r"<[^>]+>", " ", h)))


def procesar(ruta: str) -> list[dict]:
    with open(ruta, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=policy.default)
    top_dt = email.utils.parsedate_to_datetime(msg.get("Date")).date()
    top_de = _RE_CORREO.search(str(msg.get("From", "")))
    hilo = hilo_completo(cuerpo_texto(msg), top_dt, top_de.group(0) if top_de else "")

    # Una fila por adjunto con codigo: un mismo hilo puede llevar varias ofertas
    # (GD La Maria manda servicios y energia en el mismo correo).
    filas = []
    for parte in msg.walk():
        nombre = parte.get_filename()
        partes = codigo_partes(nombre) if nombre else None
        if not partes:
            continue
        consecutivo, mes, anio = partes
        d = datos_envio(hilo, mes, anio)
        filas.append({
            "archivo": os.path.basename(ruta),
            "adjunto": nombre,
            "codigo": f"No.{consecutivo:04d}-{mes}-{anio}",
            "fecha_oferta": d["fecha_oferta"].isoformat() if d["fecha_oferta"] else None,
            "seguimientos": d["seguimientos"],
            "fecha_ultima_respuesta": (d["fecha_ultima_respuesta"].isoformat()
                                       if d["fecha_ultima_respuesta"] else None),
        })
    if not filas:
        # Hilos sin adjunto con codigo (Astrea, Grupo Zambrano, Evolti): se
        # reportan con el hilo completo para resolverlos a mano.
        filas.append({
            "archivo": os.path.basename(ruta),
            "adjunto": None,
            "codigo": None,
            "hilo": [[f.isoformat(), c] for f, c in hilo],
        })
    return filas


def main():
    carpeta, salida = sys.argv[1], sys.argv[2]
    todo = []
    for f in sorted(glob.glob(os.path.join(carpeta, "*.eml"))):
        todo.extend(procesar(f))
    with open(salida, "w", encoding="utf-8") as fh:
        json.dump(todo, fh, ensure_ascii=False, indent=1)
    for fila in todo:
        print(json.dumps(fila, ensure_ascii=False))
    print(f"\n{len(todo)} filas -> {salida}")


if __name__ == "__main__":
    main()
