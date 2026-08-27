"""Captura la respuesta de `GET /comercial/proyectos-operando` como golden.

Es la precondición de la Fase 4 del refactor (`docs/refactor/06-plan-migracion.md`
§7.1 y §8): esa fase cambia de dónde lee `app/services/comercial.py`, y sin una
captura de ANTES no hay forma de demostrar que la salida no cambió.

⚠️ Conviene capturarla cuanto antes. El árbol cambia todos los días con el
trabajo normal del equipo; mientras más tarde se capture, más difícil es
distinguir "lo cambió el refactor" de "lo cambió alguien cargando datos".

SOLO LECTURA: hace un GET y escribe un archivo local. No toca la base.

Uso:
    # la base, antes de tocar nada
    python scripts/capturar_golden_operando.py https://api.ejemplo.com <TOKEN>

    # después de la Fase 4, para comparar
    python scripts/capturar_golden_operando.py https://api.ejemplo.com <TOKEN> --actual

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
DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tests", "golden")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    base_url, token = args[0].rstrip("/"), args[1]
    es_actual = "--actual" in sys.argv

    url = f"{base_url}{RUTA}"
    print(f"GET {url}")
    with httpx.Client(timeout=httpx.Timeout(15.0, read=180.0)) as cli:
        r = cli.get(url, headers={"Authorization": f"Bearer {token}"})
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
