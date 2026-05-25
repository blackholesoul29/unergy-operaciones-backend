"""
Pobla fallas_cat_categorias y fallas_cat_tipos desde
data/fallas_clasificadas_unergy.json (códigos numéricos 1.1..9.9).

Idempotente: usa INSERT … ON CONFLICT DO UPDATE.
No elimina ni desactiva los tipos antiguos para preservar FK de fallas existentes.

Uso:
    python scripts/seed_catalogo_json.py                          # BD local (.env)
    python scripts/seed_catalogo_json.py "postgresql+psycopg://..." # URL directa
    python scripts/seed_catalogo_json.py --dry-run                # solo muestra
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

args = sys.argv[1:]
DRY_RUN = "--dry-run" in args
url_args = [a for a in args if not a.startswith("--")]
DATABASE_URL = (url_args[0] if url_args else None) or os.environ.get("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    from sqlalchemy import create_engine
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    from app.core.database import engine

from sqlalchemy.orm import sessionmaker
from app.models.fallas import FallaCatCategoria, FallaCatTipo

Session = sessionmaker(bind=engine)

# ── Metadatos de categoría (código numérico → ícono + color) ─────────────────

CAT_META: dict[str, dict] = {
    "Fallas de Medición":                      {"codigo": "1", "icono": "📡", "color": "#60A5FA", "orden": 1},
    "Fallas Eléctricas":                       {"codigo": "2", "icono": "⚡", "color": "#F6FF72", "orden": 2},
    "Fallas por Eventos Adversos":             {"codigo": "3", "icono": "🌩️", "color": "#FF5757", "orden": 3},
    "Fallos por Desgaste / Degradación":       {"codigo": "4", "icono": "🔧", "color": "#F97316", "orden": 4},
    "Fallas Civiles / Estructurales":          {"codigo": "5", "icono": "🏗️", "color": "#C47AFF", "orden": 5},
    "Fallas HSE / Seguridad Laboral":          {"codigo": "6", "icono": "🦺", "color": "#4ADE80", "orden": 6},
    "Fallas BESS / Almacenamiento (si aplica)":{"codigo": "7", "icono": "🔋", "color": "#7EC8E3", "orden": 7},
    "Fallas Administrativas / Regulatorias":   {"codigo": "8", "icono": "📋", "color": "#F4A460", "orden": 8},
    "Sin Suministro Eléctrico en el Proyecto": {"codigo": "9", "icono": "🔌", "color": "#FF6B6B", "orden": 9},
}

DATA_FILE = Path(__file__).parent.parent / "data" / "fallas_clasificadas_unergy.json"


def main():
    print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Seedeando catálogo de fallas desde JSON…\n")

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    print(f"  {len(data)} entradas en el JSON")

    db = Session()
    try:
        cats_upserted = 0
        tipos_upserted = 0

        # ── Paso 1: upsert categorías ─────────────────────────────────────────
        for cat_name, meta in CAT_META.items():
            existing = db.query(FallaCatCategoria).filter_by(codigo=meta["codigo"]).first()
            if existing:
                existing.etiqueta = cat_name
                existing.icono = meta["icono"]
                existing.color_hex = meta["color"]
                existing.orden = meta["orden"]
                existing.activa = True
                print(f"  UPDATE categoría  {meta['codigo']}  {cat_name}")
            else:
                cat = FallaCatCategoria(
                    codigo=meta["codigo"],
                    etiqueta=cat_name,
                    icono=meta["icono"],
                    color_hex=meta["color"],
                    orden=meta["orden"],
                    activa=True,
                )
                if not DRY_RUN:
                    db.add(cat)
                print(f"  INSERT categoría  {meta['codigo']}  {cat_name}")
            cats_upserted += 1

        if not DRY_RUN:
            db.flush()

        # ── Paso 2: upsert tipos ──────────────────────────────────────────────
        for entry in data:
            cat_name = entry.get("Categoría", "").strip()
            code = entry.get("Código de Falla", "").strip()
            evento = entry.get("Evento", "").strip()
            desc = entry.get(
                "Descripción detallada de la actividad (requisitos, controles, documentos)", ""
            ).strip()

            if not code or not evento:
                continue

            meta = CAT_META.get(cat_name)
            if not meta:
                print(f"  WARN: categoría desconocida '{cat_name}' para código {code}")
                continue

            cat_obj = db.query(FallaCatCategoria).filter_by(codigo=meta["codigo"]).first()
            if not cat_obj:
                print(f"  WARN: categoría {meta['codigo']} no encontrada en BD, omitiendo {code}")
                continue

            existing_tipo = db.query(FallaCatTipo).filter_by(codigo=code).first()
            if existing_tipo:
                existing_tipo.etiqueta = evento
                existing_tipo.descripcion = desc
                existing_tipo.categoria_id = cat_obj.id
                existing_tipo.activa = True
                action = "UPDATE"
            else:
                tipo = FallaCatTipo(
                    categoria_id=cat_obj.id,
                    codigo=code,
                    etiqueta=evento,
                    descripcion=desc,
                    activa=True,
                )
                if not DRY_RUN:
                    db.add(tipo)
                action = "INSERT"

            tipos_upserted += 1
            print(f"  {action} tipo  {code:<8} {evento[:60]}")

        if not DRY_RUN:
            db.commit()
            print(f"\n✅  {cats_upserted} categorías y {tipos_upserted} tipos procesados.")
        else:
            print(f"\n[DRY-RUN]  {cats_upserted} categorías y {tipos_upserted} tipos se procesarían.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR — rollback: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
