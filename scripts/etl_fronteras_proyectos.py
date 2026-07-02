#!/usr/bin/env python3
"""
ETL de reconciliación fronteras.proyecto_id <-> proyectos.

Problema que resuelve: el vínculo fronteras.proyecto_id es la única fuente de
verdad que debería usarse para mapear una frontera de Quoia/ASIC a su proyecto
interno, pero se pobló en algún momento con un proceso poco confiable y quedó
con enlaces rotos (ej. "MINIGRANJA SOLAR CAÑAHUATE" apuntando al proyecto
"Baraya"). Hoy el código de resolución de nodos Quoia (app/services/mgs/
gaia_client.py) tiene que adivinar por nombre/número en cada request como
mitigación. Este script arregla la causa raíz: recalcula por nombre el
proyecto_id correcto para cada frontera y compara contra el valor actual.

Modo de uso:
  python scripts/etl_fronteras_proyectos.py                 # solo reporte (dry-run)
  python scripts/etl_fronteras_proyectos.py --csv out.csv   # además guarda CSV
  python scripts/etl_fronteras_proyectos.py --apply         # aplica los MISSING_FILLABLE
  python scripts/etl_fronteras_proyectos.py --apply --incluir-mismatch  # aplica también MISMATCH

Por seguridad, --apply NUNCA toca las filas MISMATCH a menos que se pase
también --incluir-mismatch explícitamente (esas sobreescriben un valor que ya
existía, así que requieren que un humano las haya revisado en el reporte).

Requiere DATABASE_URL en .env (ver .env.example) apuntando a la URL PÚBLICA
de Railway (con RAILWAY_TCP_PROXY_DOMAIN, no el host interno).
"""
from __future__ import annotations

import argparse
import csv
import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
import sqlalchemy as sa

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Normalización y stopwords ────────────────────────────────────────────────
# Palabras que aparecen en casi todos los nombres y no ayudan a distinguir
# un proyecto de otro (mismo criterio ya usado para el mapeo Quoia<->Solenium
# y para las keywords de gaia_client.py).
_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "y", "en",
    "minigranja", "minigranjas", "mgs", "mgr", "gd", "planta", "granja",
    "solar", "sol", "cielo", "frontera", "proyecto",
    "consumo", "auxiliar", "aux", "propio", "serv", "ser", "generacion",
}


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", s.lower()).strip()


def _core_tokens(name: str | None) -> set[str]:
    """Tokens significativos de un nombre (sin stopwords), para comparar
    identidad de proyecto ignorando ruido tipo 'Minigranja Solar' / 'Serv Aux'."""
    norm = _norm(name)
    return {t for t in norm.split() if t and t not in _STOPWORDS}


def _score(frontera_name: str, proyecto_names: list[str]) -> float:
    """Mejor score entre la frontera y cualquiera de los nombres del proyecto
    (nombre_comercial, nombre_bitacora, alias_monitoreo). Combina overlap de
    tokens (orden-independiente) con similitud de texto (tolera typos, ej.
    'BRAYA' vs 'BARAYA')."""
    f_tokens = _core_tokens(frontera_name)
    if not f_tokens:
        return 0.0
    best = 0.0
    for pname in proyecto_names:
        p_tokens = _core_tokens(pname)
        if not p_tokens:
            continue
        inter = f_tokens & p_tokens
        jaccard = len(inter) / len(f_tokens | p_tokens) if (f_tokens | p_tokens) else 0.0
        overlap = len(inter) / min(len(f_tokens), len(p_tokens))
        ratio = difflib.SequenceMatcher(None, " ".join(sorted(f_tokens)), " ".join(sorted(p_tokens))).ratio()
        score = max(jaccard, overlap * 0.85, ratio)  # overlap se castiga un poco: puede inflarse con sets chicos
        best = max(best, score)
    return round(best, 3)


UMBRAL_ACEPTAR = 0.55
MARGEN_AMBIGUO = 0.05


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="Ruta donde guardar el reporte completo en CSV")
    ap.add_argument("--apply", action="store_true", help="Aplica los UPDATE de las filas MISSING_FILLABLE")
    ap.add_argument("--incluir-mismatch", action="store_true", help="Con --apply, también corrige las MISMATCH")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: falta DATABASE_URL en .env")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine = sa.create_engine(url)
    with engine.connect() as conn:
        fronteras = conn.execute(sa.text(
            "SELECT id, nombre_frontera, tipo_frontera, proyecto_id, codigo_frontera "
            "FROM fronteras ORDER BY id"
        )).mappings().all()
        proyectos = conn.execute(sa.text(
            "SELECT id, nombre_comercial, nombre_bitacora, alias_monitoreo, estado "
            "FROM proyectos"
        )).mappings().all()

    proyecto_por_id = {p["id"]: p for p in proyectos}
    candidatos = [
        (p["id"], [p["nombre_comercial"], p["nombre_bitacora"], p["alias_monitoreo"]])
        for p in proyectos
    ]

    filas = []
    for f in fronteras:
        puntajes = [(pid, _score(f["nombre_frontera"], names)) for pid, names in candidatos]
        puntajes.sort(key=lambda x: -x[1])
        mejor_id, mejor_score = puntajes[0] if puntajes else (None, 0.0)
        segundo_score = puntajes[1][1] if len(puntajes) > 1 else 0.0

        actual_id = f["proyecto_id"]
        nombre_actual = proyecto_por_id.get(actual_id, {}).get("nombre_comercial") if actual_id else None

        if mejor_score < UMBRAL_ACEPTAR:
            veredicto = "UNRESOLVED"
            sugerido_id, sugerido_nombre = None, None
        elif (mejor_score - segundo_score) < MARGEN_AMBIGUO and segundo_score >= UMBRAL_ACEPTAR:
            veredicto = "AMBIGUOUS"
            sugerido_id, sugerido_nombre = mejor_id, proyecto_por_id[mejor_id]["nombre_comercial"]
        else:
            sugerido_id = mejor_id
            sugerido_nombre = proyecto_por_id[mejor_id]["nombre_comercial"]
            if actual_id is None:
                veredicto = "MISSING_FILLABLE"
            elif actual_id == sugerido_id:
                veredicto = "MATCH"
            else:
                veredicto = "MISMATCH"

        filas.append({
            "frontera_id": f["id"],
            "codigo_frontera": f["codigo_frontera"],
            "nombre_frontera": f["nombre_frontera"],
            "tipo_frontera": f["tipo_frontera"],
            "proyecto_id_actual": actual_id,
            "nombre_proyecto_actual": nombre_actual,
            "proyecto_id_sugerido": sugerido_id,
            "nombre_proyecto_sugerido": sugerido_nombre,
            "score": mejor_score,
            "veredicto": veredicto,
        })

    # ── Resumen ──────────────────────────────────────────────────────────────
    conteo: dict[str, int] = {}
    for r in filas:
        conteo[r["veredicto"]] = conteo.get(r["veredicto"], 0) + 1
    print("=== Resumen ===")
    for k in ("MATCH", "MISSING_FILLABLE", "MISMATCH", "AMBIGUOUS", "UNRESOLVED"):
        print(f"  {k}: {conteo.get(k, 0)}")
    print()

    for veredicto in ("MISMATCH", "AMBIGUOUS", "UNRESOLVED", "MISSING_FILLABLE"):
        filas_v = [r for r in filas if r["veredicto"] == veredicto]
        if not filas_v:
            continue
        print(f"=== {veredicto} ({len(filas_v)}) ===")
        for r in filas_v:
            print(f"  frontera#{r['frontera_id']:>4} [{r['tipo_frontera']:<16}] '{r['nombre_frontera']}'"
                  f"\n      actual:    proyecto#{r['proyecto_id_actual']} {r['nombre_proyecto_actual']!r}"
                  f"\n      sugerido:  proyecto#{r['proyecto_id_sugerido']} {r['nombre_proyecto_sugerido']!r}  (score={r['score']})")
        print()

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
            w.writeheader()
            w.writerows(filas)
        print(f"CSV guardado en: {args.csv}")

    if args.apply:
        objetivo = {"MISSING_FILLABLE"} | ({"MISMATCH"} if args.incluir_mismatch else set())
        a_aplicar = [r for r in filas if r["veredicto"] in objetivo]
        if not a_aplicar:
            print("Nada que aplicar.")
            return
        print(f"\nAplicando {len(a_aplicar)} UPDATE(s)...")
        with engine.begin() as conn:
            for r in a_aplicar:
                conn.execute(
                    sa.text("UPDATE fronteras SET proyecto_id = :pid WHERE id = :fid"),
                    {"pid": r["proyecto_id_sugerido"], "fid": r["frontera_id"]},
                )
        print("Listo.")
    else:
        print("(dry-run — no se escribió nada; corre con --apply para aplicar MISSING_FILLABLE)")


if __name__ == "__main__":
    main()
