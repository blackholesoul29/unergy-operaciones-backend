"""Carga el corpus de XM a las tablas del Modelo Predictivo.

Uso:
    python scripts/cargar_corpus_garantias.py --zip "<ruta al zip>" [--dry-run]

Idempotente: reingerir el mismo zip no duplica filas -- `xm_archivo.sha256` es unico y
`xm_medida` tiene su clave natural.

Solo carga `.tx2`, que es la version que usa la replica. El `.tx1` habilita estimar
antes del dia 14 y entra en el plan 4, con su propio lag medido.
"""
import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.garantias_modelo import XMArchivo, XMMedida  # noqa: E402
from app.services.garantias_modelo.cargador import (  # noqa: E402
    agregar_por_clave_natural, disponible_desde_derivado, filas_a_medidas,
)
from app.services.garantias_modelo.ingesta import preparar_archivo  # noqa: E402
from app.services.garantias_modelo.normalizar import version_de_nombre  # noqa: E402
from app.services.garantias_modelo.parsers_ftp import (  # noqa: E402
    parsear_arrpas, parsear_balcttos, parsear_dspcttos, parsear_trsd,
)

AGENTES = ("UNGG", "UNGC")
VERSION_OBJETIVO = "tx2"


def _parsear(tipo, contenido, fecha, version, agente):
    if tipo == "balcttos":
        return parsear_balcttos(contenido, fecha, version, agente)
    if tipo == "trsd":
        return parsear_trsd(contenido, fecha, version)
    if tipo == "dspcttos":
        return parsear_dspcttos(contenido, fecha, version, agente)
    if tipo == "arrpas":
        return parsear_arrpas(contenido, fecha, version)
    return [], 0


def _anio_de_ruta(nombre_en_zip):
    """Los zips agrupan por carpeta `AAAA-MM`; el nombre del archivo solo trae MMDD."""
    carpeta = os.path.dirname(nombre_en_zip).split("/")[-1]
    partes = carpeta.split("-")
    if len(partes) == 2 and partes[0].isdigit() and len(partes[0]) == 4:
        return int(partes[0])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--agente", default="UNGG", choices=AGENTES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # En seco no se abre sesion: el sentido de --dry-run es validar el corpus, y
    # exigir una base para eso lo vuelve inutil justo cuando mas sirve (antes de
    # tener el esquema creado en local).
    db = None if args.dry_run else SessionLocal()
    nuevos = saltados = rechazados = medidas = agregadas = 0
    try:
        with zipfile.ZipFile(args.zip) as zf:
            for n in sorted(zf.namelist()):
                if n.endswith("/"):
                    continue
                base = os.path.basename(n)
                version = version_de_nombre(base)
                if version != VERSION_OBJETIVO:
                    continue

                anio = _anio_de_ruta(n)
                contenido = zf.read(n)

                # Dos pasadas, y no es redundancia. Con `disponible_desde=None`
                # `preparar_archivo` corta ANTES de llamar a `validar_estructura`:
                # devuelve `esquema_ok=False` sin haber mirado una sola columna. Si
                # repusieramos el flag a mano despues, marcariamos como valido un
                # archivo que nunca se valido -- y el fallo de abril-2026 (columnas
                # intercambiadas) volveria a pasar inadvertido.
                #
                # La primera pasada sirve solo para derivar la fecha del documento;
                # la segunda, ya con `disponible_desde`, es la que valida de verdad.
                previo = preparar_archivo(base, contenido,
                                          disponible_desde=None, anio=anio)
                if not previo["periodo_ini"]:
                    rechazados += 1
                    print(f"  SIN FECHA {base}: no se pudo derivar el dia del nombre")
                    continue

                meta = preparar_archivo(
                    base, contenido, anio=anio,
                    disponible_desde=disponible_desde_derivado(
                        previo["periodo_ini"], version))
                meta["origen_disponibilidad"] = "derivado"

                if db is not None:
                    existe = (db.query(XMArchivo)
                              .filter_by(sha256=meta["sha256"]).first())
                    if existe:
                        saltados += 1
                        continue
                if not meta["esquema_ok"]:
                    rechazados += 1
                    print(f"  RECHAZADO {base}: {meta['esquema_detalle']}")
                    continue

                filas, descartadas = _parsear(
                    meta["tipo"], contenido, meta["periodo_ini"], version, args.agente)
                if descartadas:
                    print(f"  {base}: {descartadas} fila(s) truncada(s) descartada(s)")

                # BalCttos trae una linea por contrato y varias comparten CONCEPTO:
                # sin agregar, el INSERT choca contra uq_xm_medida_natural.
                filas, colapsadas = agregar_por_clave_natural(filas)
                agregadas += colapsadas

                nuevos += 1
                medidas += len(filas)
                if args.dry_run:
                    continue

                arch = XMArchivo(**meta)
                arch.filas_ingeridas = len(filas)
                db.add(arch)
                db.flush()
                db.bulk_insert_mappings(
                    XMMedida, filas_a_medidas(filas, archivo_id=arch.id))
                db.commit()
    finally:
        if db is not None:
            db.close()

    modo = "SIMULACION" if args.dry_run else "CARGA"
    print(f"\n[{modo}] nuevos: {nuevos}   ya estaban: {saltados}   "
          f"rechazados: {rechazados}")
    print(f"medidas: {medidas:,}   (filas sumadas por clave repetida: {agregadas:,})")
    if rechazados:
        print("Hubo archivos rechazados. Revisar antes de dar la carga por buena.")
        sys.exit(1)


if __name__ == "__main__":
    main()
