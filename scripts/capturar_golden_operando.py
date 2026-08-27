"""Captura la respuesta de `GET /comercial/proyectos-operando` como golden.

Es la precondición de la Fase 4 del refactor (`docs/refactor/06-plan-migracion.md`
§7.1 y §8): esa fase cambia de dónde lee `app/services/comercial.py`, y sin una
captura de ANTES no hay forma de demostrar que la salida no cambió.

⚠️ Conviene capturarla cuanto antes. El árbol cambia todos los días con el
trabajo normal del equipo; mientras más tarde se capture, más difícil es
distinguir "lo cambió el refactor" de "lo cambió alguien cargando datos".

SOLO LECTURA: hace un GET y escribe un archivo local. No toca la base.

EL TOKEN NUNCA VA EN LA LÍNEA DE COMANDOS. Queda en el historial del shell y
en los logs de proceso. El script lo pide pegado por teclado, sin eco, o lo lee
de una variable de entorno si preferís exportarla.

Uso:
    # la base, antes de tocar nada. Pide la credencial al arrancar.
    python scripts/capturar_golden_operando.py

    # contra otra URL
    python scripts/capturar_golden_operando.py https://otra-api.ejemplo.com

    # después de la Fase 4, para comparar contra la base
    python scripts/capturar_golden_operando.py --actual

Credencial, por orden de preferencia:
    1. Nada: el script la pide con `getpass` y no se ve al teclearla.
    2. `OPS_API_KEY` en el entorno -> se manda como header `X-API-Key`.
    3. `OPS_TOKEN` en el entorno   -> se manda como `Authorization: Bearer`.

Y después:
    python -m pytest tests/test_golden_operando.py -q

El archivo va a `tests/golden/`, que está fuera de git: la respuesta trae datos
de clientes y contratos, y este repositorio es público.
"""
import json
import os
import sys
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    sys.exit("Falta httpx: python -m pip install httpx")

RUTA = "/api/v1/comercial/proyectos-operando"
BASE_POR_DEFECTO = "https://backend-production-63d8.up.railway.app"
DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tests", "golden")


def _credencial() -> tuple[dict, str]:
    """El header de autenticación y de dónde salió la credencial.

    Nunca por argv: ahí queda en el historial del shell y en la lista de
    procesos. Del entorno si está, y si no, pegada a mano sin eco.
    """
    import getpass

    if os.environ.get("OPS_API_KEY"):
        return {"X-API-Key": os.environ["OPS_API_KEY"]}, "OPS_API_KEY"
    if os.environ.get("OPS_TOKEN"):
        return {"Authorization": f"Bearer {os.environ['OPS_TOKEN']}"}, "OPS_TOKEN"

    print("Pegá el token JWT (localStorage['token'] del frontend) o una API key.")
    print("No se va a ver mientras lo pegás, y no queda en el historial.")
    secreto = getpass.getpass("credencial: ").strip()
    if not secreto:
        sys.exit("Sin credencial no hay captura.")
    # Un JWT son tres partes separadas por punto y empieza por 'ey' (el
    # '{"alg"' en base64). Cualquier otra cosa se trata como API key.
    if secreto.count(".") == 2 and secreto.startswith("ey"):
        return {"Authorization": f"Bearer {secreto}"}, "JWT pegado"
    return {"X-API-Key": secreto}, "API key pegada"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) > 1:
        sys.exit(__doc__)
    base_url = (args[0] if args else BASE_POR_DEFECTO).rstrip("/")
    es_actual = "--actual" in sys.argv

    headers, origen = _credencial()

    url = f"{base_url}{RUTA}"
    print(f"GET {url}   (credencial: {origen})")
    with httpx.Client(timeout=httpx.Timeout(15.0, read=180.0)) as cli:
        r = cli.get(url, headers=headers)
    if r.status_code == 401:
        sys.exit("HTTP 401: la credencial no sirve. Si es un JWT, seguro expiró "
                 "-- volvé a copiarlo del navegador.")
    if r.status_code != 200:
        sys.exit(f"HTTP {r.status_code}: {r.text[:400]}")

    payload = r.json()

    # El commit importa: un golden sin saber contra qué código se capturó no
    # sirve para atribuir una diferencia.
    commit = os.popen("git rev-parse --short HEAD").read().strip() or None

    captura = {
        "capturado_en": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "commit": commit,
        "respuesta": payload,
    }

    os.makedirs(DESTINO, exist_ok=True)
    nombre = "proyectos_operando_actual.json" if es_actual else "proyectos_operando.json"
    ruta = os.path.join(DESTINO, nombre)
    if os.path.exists(ruta) and not es_actual:
        # La base se captura UNA vez. Pisarla sin querer es perder la referencia.
        sys.exit(f"Ya existe {ruta}.\nSi de verdad querés reemplazar la base, "
                 f"borrala a mano primero -- es la referencia de la Fase 4.")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(captura, fh, ensure_ascii=False, indent=2, default=str)

    # Un conteo a la vista: un golden vacío pasa todos los tests y no protege nada.
    sys.path.insert(0, os.path.join(os.path.dirname(DESTINO), "tests"))
    from golden_operando import plantas, revisar_invariantes
    n = len(plantas(payload))
    fallas = revisar_invariantes(payload)

    print(f"Escrito: {ruta}")
    print(f"  nodos raíz: {len(payload) if isinstance(payload, list) else 1}")
    print(f"  plantas:    {n}")
    print(f"  commit:     {commit}")
    if n == 0:
        print("  ⚠️  CERO plantas: esta captura no protege nada, revisá el token y los filtros")
    if fallas:
        print(f"  ⚠️  la captura YA viola {len(fallas)} invariantes -- son bugs de hoy, "
              f"no del refactor:")
        for f in fallas[:10]:
            print(f"      {f}")


if __name__ == "__main__":
    main()
