"""
Revisión humana de resoluciones de falla emparejadas con baja confianza.

`migrate_fallas_desde_sheets.py` empareja el texto libre de "Tipo Resolución" contra
el catálogo con similitud difusa (app/utils/falla_resolution_matcher.py). Cuando la
confianza queda por debajo del umbral, la falla se migra con resolución 'otro' y el
item se encola en un archivo de revisión (por defecto `fallas_pending_review.json`).

Esta migración escribe vía API REST, no directamente en la BD, así que la cola de
revisión vive en ese archivo (no en columnas de la tabla). Este script cierra el
"human-in-the-loop": muestra cada caso pendiente y deja que un operador confirme la
sugerencia o la corrija, escribiendo un archivo de decisiones que luego puede
aplicarse contra la API.

Uso:
    python scripts/review_fallas_pending.py                 # revisión interactiva
    python scripts/review_fallas_pending.py --list          # solo listar, sin decidir
    python scripts/review_fallas_pending.py --input x.json --output y.json
"""
import argparse
import json
import os
import sys

# Códigos válidos del catálogo de resoluciones (fallas_cat_resoluciones).
CODIGOS_VALIDOS = [
    "reinicio_inversor",
    "visita_tecnica",
    "cambio_componente",
    "actualizacion_fw",
    "intervencion_red",
    "resolucion_remota",
    "sin_accion",
    "otro",
]

DEFAULT_INPUT = os.environ.get("FALLAS_REVIEW_OUTPUT", "fallas_pending_review.json")
DEFAULT_OUTPUT = "fallas_pending_resolved.json"


def cargar_pendientes(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(
            f"No existe el archivo de revisión '{path}'.\n"
            "Corre primero la migración (genera la cola de baja confianza) o pasa "
            "--input con la ruta correcta."
        )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        sys.exit(f"Formato inesperado en '{path}': se esperaba una lista JSON.")
    return data


def mostrar(item: dict, idx: int, total: int) -> None:
    print("\n" + "-" * 60)
    print(f"  [{idx}/{total}]  falla legado: {item.get('codigo_legado') or '(sin ID)'}")
    print(f"  Texto original : {item.get('texto_original')!r}")
    print(f"  Sugerencia     : {item.get('codigo_sugerido') or '(ninguna)'}")
    print(f"  Confianza      : {item.get('confianza')}%")


def listar(pendientes: list[dict]) -> None:
    total = len(pendientes)
    for i, item in enumerate(pendientes, 1):
        mostrar(item, i, total)
    print("\n" + "-" * 60)
    print(f"  {total} resoluciones pendientes de revisión.")


def pedir_codigo(sugerido: str | None) -> str:
    """Lee un código del operador; Enter acepta la sugerencia."""
    opciones = ", ".join(CODIGOS_VALIDOS)
    while True:
        prompt = (
            f"  Código correcto [Enter = {sugerido or 'otro'}] "
            f"(s=saltar): "
        )
        try:
            resp = input(prompt).strip()
        except EOFError:
            # entorno no interactivo: acepta la sugerencia por defecto
            return sugerido or "otro"
        if resp == "":
            return sugerido or "otro"
        if resp.lower() == "s":
            return ""  # saltar
        if resp in CODIGOS_VALIDOS:
            return resp
        print(f"    Código inválido. Válidos: {opciones}")


def revisar(pendientes: list[dict], output: str) -> None:
    total = len(pendientes)
    decisiones: list[dict] = []
    for i, item in enumerate(pendientes, 1):
        mostrar(item, i, total)
        codigo = pedir_codigo(item.get("codigo_sugerido"))
        if not codigo:
            print("    → saltada")
            continue
        decisiones.append({
            "codigo_legado": item.get("codigo_legado"),
            "texto_original": item.get("texto_original"),
            "codigo_confirmado": codigo,
        })
        print(f"    → confirmada como '{codigo}'")

    with open(output, "w", encoding="utf-8") as fh:
        json.dump(decisiones, fh, ensure_ascii=False, indent=2)
    print("\n" + "=" * 60)
    print(f"  {len(decisiones)} decisiones guardadas en {output}")
    print(f"  ({total - len(decisiones)} saltadas)")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help=f"archivo de pendientes (def: {DEFAULT_INPUT})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help=f"archivo de decisiones (def: {DEFAULT_OUTPUT})")
    parser.add_argument("--list", action="store_true",
                        help="solo listar pendientes, sin decidir")
    args = parser.parse_args()

    pendientes = cargar_pendientes(args.input)
    if not pendientes:
        print("No hay resoluciones pendientes de revisión. 🎉")
        return

    if args.list:
        listar(pendientes)
    else:
        revisar(pendientes, args.output)


if __name__ == "__main__":
    main()
