"""Prueba GET /fallas/por-proyecto contra PRODUCCION con una API Key real.

Es de SOLO LECTURA: no crea, no modifica y no borra nada. Se puede correr con
la key de cualquier consumidor para confirmar que la integracion le responde.

    export UNERGY_API_KEY=uop_...
    python scripts/pruebas_api_fallas/probar_prod.py --proyecto-id 42
    python scripts/pruebas_api_fallas/probar_prod.py --nombre "Santa Fe 2"
    python scripts/pruebas_api_fallas/probar_prod.py --api-id SF2 --json
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("UNERGY_API_BASE", "https://backend-production-63d8.up.railway.app")
RUTA = "/api/v1/fallas/por-proyecto"
GRUPOS = ("vigente", "programado", "terminado", "todas")


def pedir(key: str, params: dict) -> tuple[int, dict]:
    url = f"{BASE}{RUTA}?" + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(cuerpo)
        except json.JSONDecodeError:
            return e.code, {"detail": cuerpo}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--proyecto-id", type=int)
    g.add_argument("--api-id", help="sub_project / api_id_unergy de la planta")
    g.add_argument("--nombre", help="nombre exacto de la planta")
    ap.add_argument("--estado", choices=GRUPOS, help="por defecto recorre los cuatro")
    ap.add_argument("--desde"), ap.add_argument("--hasta")
    ap.add_argument("--json", action="store_true", help="imprime la respuesta cruda")
    a = ap.parse_args()

    key = os.environ.get("UNERGY_API_KEY")
    if not key:
        print("Falta la variable de entorno UNERGY_API_KEY.", file=sys.stderr)
        return 2

    llave = {"proyecto_id": a.proyecto_id, "api_id_unergy": a.api_id, "nombre": a.nombre}
    grupos = (a.estado,) if a.estado else GRUPOS
    print(f"{BASE}{RUTA}\n")

    problemas = []
    resumen_visto = None
    for grupo in grupos:
        codigo, cuerpo = pedir(key, {**llave, "estado": grupo,
                                     "desde": a.desde, "hasta": a.hasta, "size": 1000})
        if codigo != 200:
            print(f"  {grupo:<11} HTTP {codigo}  {cuerpo.get('detail')}")
            problemas.append(grupo)
            continue
        planta = cuerpo["proyecto"]
        if resumen_visto is None:
            resumen_visto = cuerpo["resumen"]
            print(f"  Planta: {planta['nombre']} (id={planta['id']}, "
                  f"api_id_unergy={planta['api_id_unergy']})")
            print(f"  Resumen: {resumen_visto}\n")
        print(f"  {grupo:<11} {cuerpo['total']:>4} falla(s)   "
              f"estados: {', '.join(cuerpo['estados_incluidos'])}")
        for f in cuerpo["items"][:3]:
            extra = f"  programada: {f['fecha_programada']}" if f["fecha_programada"] else ""
            print(f"      {f['codigo']}  {f['fecha_identificacion']}  "
                  f"[{f['estado']['codigo']}]  {(f['descripcion'] or '')[:60]}{extra}")
        if len(cuerpo["items"]) > 3:
            print(f"      ... y {len(cuerpo['items']) - 3} mas")
        if a.json:
            print(json.dumps(cuerpo, indent=2, ensure_ascii=False))

    # La suma de las tres cubetas tiene que dar el total: si no, algun estado
    # del catalogo se quedo sin clasificar y hay fallas invisibles.
    if resumen_visto:
        suma = sum(resumen_visto[g] for g in ("vigente", "programado", "terminado"))
        if suma != resumen_visto["total"]:
            print(f"\n  OJO: las cubetas suman {suma} pero el total es "
                  f"{resumen_visto['total']} -- hay fallas sin clasificar.")
            problemas.append("resumen")

    print("\n" + ("Todo respondio bien." if not problemas else f"Problemas en: {problemas}"))
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
