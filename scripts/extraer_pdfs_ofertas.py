"""Saca a disco los PDFs de oferta adjuntos en los .eml, para subirlos a Drive.

Solo PDFs cuyo nombre trae código de oferta: descarta contratos .docx, imágenes
de firma y el 'Respuesta XM.pdf'. Imprime el código de cada uno para poder
pegar después el link de Drive en el campo documento_url de esa oferta.

Uso (Windows):
    set PYTHONIOENCODING=utf-8
    python scripts/extraer_pdfs_ofertas.py "C:\\...\\Ofertas\\Correos" "C:\\...\\Ofertas\\PDFs"
"""
import email
import glob
import os
import sys
from email import policy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.utils.correos_hilo import codigo_partes  # noqa: E402


def main():
    carpeta, destino = sys.argv[1], sys.argv[2]
    os.makedirs(destino, exist_ok=True)
    n = 0
    for f in sorted(glob.glob(os.path.join(carpeta, "*.eml"))):
        with open(f, "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=policy.default)
        for parte in msg.walk():
            nombre = parte.get_filename()
            if not nombre or not nombre.lower().endswith(".pdf"):
                continue
            partes = codigo_partes(nombre)
            if not partes:
                continue
            with open(os.path.join(destino, nombre), "wb") as out:
                out.write(parte.get_payload(decode=True))
            n += 1
            cons, mes, anio = partes
            print(f"No.{cons:04d}-{mes}-{anio}  <-  {nombre}")
    print(f"\n{n} PDFs -> {destino}")


if __name__ == "__main__":
    main()
