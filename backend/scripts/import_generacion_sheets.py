#!/usr/bin/env python3
"""
Importa datos de generación diaria desde Google Sheets hacia PostgreSQL.

Requisitos:
    pip install gspread google-auth pandas requests

Uso:
    cd backend
    python scripts/import_generacion_sheets.py \
        --sheet-id 1ABC...XYZ \
        --hoja "Generacion" \
        --col-proyecto "Proyecto" \
        --col-fecha "Fecha" \
        --col-kwh-real "kWh Real" \
        --col-kwh-p90 "kWh P90" \
        [--overwrite]

Variables de entorno necesarias:
    DATABASE_URL       — misma que usa el backend FastAPI
    GOOGLE_SA_JSON     — ruta al JSON de cuenta de servicio de Google
                         (opcional si el sheet es público)

Estrategia de matching de proyectos:
    1. Exacto sobre nombre_comercial
    2. Exacto sobre alias_monitoreo (separados por |)
    3. Partial / fuzzy (SequenceMatcher >= 0.75)
"""
import argparse
import os
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Añadir el directorio raíz del backend al path para poder importar la app
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.models.generacion import GeneracionDiaria
from app.models.proyectos import Proyecto
from app.utils.proyecto_matching import find_proyecto_by_name


# ── configuración ────────────────────────────────────────────────────────────

def get_db_session() -> Session:
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _parse_date(s) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(s) -> Decimal | None:
    if s is None or str(s).strip() in ("", "-", "N/A", "n/a"):
        return None
    try:
        return Decimal(str(s).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None


# ── lectura desde Google Sheets ──────────────────────────────────────────────

def read_sheet_gspread(sheet_id: str, hoja: str, sa_json: str | None) -> list[dict]:
    """Lee la hoja usando gspread (requiere API credentials)."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("ERROR: instala gspread y google-auth:  pip install gspread google-auth")
        sys.exit(1)

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    if sa_json:
        creds = Credentials.from_service_account_file(sa_json, scopes=scopes)
        gc = gspread.authorize(creds)
    else:
        gc = gspread.oauth()  # flujo OAuth interactivo

    sheet = gc.open_by_key(sheet_id)
    ws = sheet.worksheet(hoja)
    return ws.get_all_records()


def read_sheet_public(sheet_id: str, gid: str = "0") -> list[dict]:
    """Lee una hoja pública usando la API de Google Visualization (sin auth)."""
    try:
        import requests
        import json
        import re
    except ImportError:
        print("ERROR: instala requests:  pip install requests")
        sys.exit(1)

    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:json&gid={gid}&headers=1"
    )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    # La respuesta tiene un prefijo no-JSON que hay que quitar
    raw = re.sub(r"^[^{]+", "", resp.text).rstrip(");")
    data = json.loads(raw)

    cols = [c["label"] for c in data["table"]["cols"]]
    rows = []
    for row in data["table"].get("rows", []):
        rec = {}
        for i, cell in enumerate(row.get("c", [])):
            val = cell.get("v") if cell else None
            rec[cols[i]] = val
        rows.append(rec)
    return rows


# ── importación ──────────────────────────────────────────────────────────────

def import_rows(
    db: Session,
    rows: list[dict],
    col_proyecto: str,
    col_fecha: str,
    col_kwh_real: str,
    col_kwh_p90: str,
    col_kwh_auto: str | None,
    fuente: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    insertados = actualizados = omitidos = errores = 0
    proyecto_cache: dict[str, Proyecto | None] = {}

    for i, row in enumerate(rows, 1):
        nombre_ext = str(row.get(col_proyecto) or "").strip()
        fecha = _parse_date(row.get(col_fecha))

        if not nombre_ext or not fecha:
            omitidos += 1
            if not nombre_ext:
                print(f"  [fila {i}] omitida: sin nombre de proyecto")
            else:
                print(f"  [fila {i}] omitida ({nombre_ext}): fecha inválida '{row.get(col_fecha)}'")
            continue

        if nombre_ext not in proyecto_cache:
            proyecto_cache[nombre_ext] = find_proyecto_by_name(db, nombre_ext)

        proyecto = proyecto_cache[nombre_ext]
        if not proyecto:
            print(f"  [fila {i}] WARN: no se encontró proyecto para '{nombre_ext}' — omitida")
            errores += 1
            continue

        kwh_real = _parse_decimal(row.get(col_kwh_real))
        kwh_p90 = _parse_decimal(row.get(col_kwh_p90))
        kwh_auto = _parse_decimal(row.get(col_kwh_auto)) if col_kwh_auto else None

        existing = db.query(GeneracionDiaria).filter(
            GeneracionDiaria.proyecto_id == proyecto.id,
            GeneracionDiaria.fecha == fecha,
        ).first()

        if existing:
            if overwrite:
                if not dry_run:
                    if kwh_real is not None:
                        existing.kwh_real = kwh_real
                    if kwh_p90 is not None:
                        existing.kwh_p90 = kwh_p90
                    if kwh_auto is not None:
                        existing.kwh_autoconsumo = kwh_auto
                    existing.fuente = fuente
                actualizados += 1
                print(f"  [fila {i}] UPDATE {proyecto.nombre_comercial} {fecha} real={kwh_real} p90={kwh_p90}")
            else:
                omitidos += 1
        else:
            if not dry_run:
                rec = GeneracionDiaria(
                    proyecto_id=proyecto.id,
                    fecha=fecha,
                    kwh_real=kwh_real,
                    kwh_p90=kwh_p90,
                    kwh_autoconsumo=kwh_auto,
                    fuente=fuente,
                )
                db.add(rec)
            insertados += 1
            print(f"  [fila {i}] INSERT {proyecto.nombre_comercial} {fecha} real={kwh_real} p90={kwh_p90}")

    if not dry_run:
        db.commit()

    print(f"\nResultado: {insertados} insertados | {actualizados} actualizados | {omitidos} omitidos | {errores} errores")
    if dry_run:
        print("(DRY RUN — no se escribió nada en la base de datos)")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Importar generacion desde Google Sheets")
    parser.add_argument("--sheet-id", required=True, help="ID del Google Sheet (en la URL)")
    parser.add_argument("--hoja", default="Generacion", help="Nombre de la hoja/pestaña")
    parser.add_argument("--gid", default="0", help="GID de la hoja (para lectura pública)")
    parser.add_argument("--col-proyecto", default="Proyecto", help="Columna con nombre del proyecto")
    parser.add_argument("--col-fecha", default="Fecha", help="Columna con la fecha")
    parser.add_argument("--col-kwh-real", default="kWh Real", help="Columna kWh real generados")
    parser.add_argument("--col-kwh-p90", default="kWh P90", help="Columna kWh P90 esperados")
    parser.add_argument("--col-kwh-auto", default=None, help="Columna kWh autoconsumo (opcional)")
    parser.add_argument("--fuente", default="sheets", help="Valor para campo fuente (ej: sheets, importacion)")
    parser.add_argument("--overwrite", action="store_true", help="Sobreescribir registros existentes")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin escribir en BD")
    parser.add_argument("--publico", action="store_true", help="Sheet público (sin credenciales)")
    parser.add_argument("--sa-json", default=os.getenv("GOOGLE_SA_JSON"), help="Ruta al JSON de cuenta de servicio")
    args = parser.parse_args()

    print(f"Conectando a la base de datos...")
    db = get_db_session()

    print(f"Leyendo hoja '{args.hoja}' del Sheet {args.sheet_id}...")
    if args.publico:
        rows = read_sheet_public(args.sheet_id, args.gid)
    else:
        rows = read_sheet_gspread(args.sheet_id, args.hoja, args.sa_json)

    print(f"  {len(rows)} filas encontradas")
    if not rows:
        print("No hay datos para importar.")
        return

    print(f"\nImportando{' (DRY RUN)' if args.dry_run else ''}...")
    import_rows(
        db=db,
        rows=rows,
        col_proyecto=args.col_proyecto,
        col_fecha=args.col_fecha,
        col_kwh_real=args.col_kwh_real,
        col_kwh_p90=args.col_kwh_p90,
        col_kwh_auto=args.col_kwh_auto,
        fuente=args.fuente,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    db.close()


if __name__ == "__main__":
    main()
