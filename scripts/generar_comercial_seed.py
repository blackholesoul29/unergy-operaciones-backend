"""Genera data/comercial_seed.json a partir del Google Sheets comercial (export XLSX).

Uso:
    python scripts/generar_comercial_seed.py ruta/al/libro.xlsx

Lee las hojas de prospección y emite una fila por oferta:
  - 'Servicios Operaciones ' → tipo servicios_operacionales
  - 'Comercialización de Energía' → tipo compra_energia
  - 'Comunidades' → tipo comunidad_energetica
Salta filas sin empresa. Limpia viñetas/espacios. El consumo lo hace el endpoint
admin POST /comercial/importar-hojas (idempotente por numero_oferta).
"""
import json
import re
import sys
from pathlib import Path

import openpyxl


def clean(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").replace("\t", " ").replace("•", " • ")
    s = re.sub(r"\s+", " ", s).strip(" •").strip()
    return s or None


def _rows(ws):
    it = ws.iter_rows(values_only=True)
    next(it, None)  # descarta encabezado
    yield from it


def generar(xlsx_path: str) -> list[dict]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    seed: list[dict] = []

    # Servicios Operaciones: 0 # | 1 Consecutivo | 2 Empresa | 3 Proyecto |
    #                        4 Servicios | 5 Etapa | 6 FPO | 7 Precio | 8 Contrato | 9 Fecha
    for r in _rows(wb["Servicios Operaciones "]):
        emp = clean(r[2]) if len(r) > 2 else None
        if not emp:
            continue
        seed.append({
            "hoja": "servicios_operaciones", "tipo": "servicios_operacionales",
            "empresa": emp, "planta_nombre": clean(r[3]) if len(r) > 3 else None,
            "servicios_buscados": clean(r[4]) if len(r) > 4 else None,
            "etapa_texto": clean(r[5]) if len(r) > 5 else None,
            "numero_oferta": clean(r[1]) if len(r) > 1 else None,
            "precio_detalle": clean(r[7]) if len(r) > 7 else None,
            "contrato_firmado": clean(r[8]) if len(r) > 8 else None,
            "fecha_oferta": clean(r[9]) if len(r) > 9 else None,
        })

    # Comercialización de Energía: 0 # | 1 Consecutivo | 2 Empresa | 3 Proyecto |
    #                              4 Tiempo | 5 Tipo Contrato | 6 Etapa | 7 Precio
    for r in _rows(wb["Comercialización de Energía"]):
        emp = clean(r[2]) if len(r) > 2 else None
        if not emp:
            continue
        seed.append({
            "hoja": "comercializacion_energia", "tipo": "compra_energia",
            "empresa": emp, "planta_nombre": clean(r[3]) if len(r) > 3 else None,
            "tiempo": clean(r[4]) if len(r) > 4 else None,
            "tipo_contrato": clean(r[5]) if len(r) > 5 else None,
            "etapa_texto": clean(r[6]) if len(r) > 6 else None,
            "numero_oferta": clean(r[1]) if len(r) > 1 else None,
            "precio_detalle": clean(r[7]) if len(r) > 7 else None,
        })

    # Comunidades: 0 # | 1 Consecutivo | 2 Empresa | 3 Etapa
    for r in _rows(wb["Comunidades"]):
        emp = clean(r[2]) if len(r) > 2 else None
        if not emp:
            continue
        seed.append({
            "hoja": "comunidades", "tipo": "comunidad_energetica",
            "empresa": emp, "etapa_texto": clean(r[3]) if len(r) > 3 else None,
            "numero_oferta": clean(r[1]) if len(r) > 1 else None,
        })

    return seed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    data = generar(sys.argv[1])
    out = Path("data/comercial_seed.json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Escritas {len(data)} filas en {out}")
