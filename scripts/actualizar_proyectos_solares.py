"""
Actualiza campos de proyectos desde data/proyectos_solares_completo.json
y el mapeo de Operadores de Red.

Campos que se llenan:
  proyectos.departamento           ← json.departamento
  proyectos.municipio              ← json.ciudad
  proyectos.potencia_instalada_kwp ← json.potencia_instalada_dc_kwp
  proyecto_info_tecnica.cantidad_total_paneles ← json.numero_de_paneles
  proyectos.operador_red           ← mapeo OR hardcodeado

Uso:
    cd unergy-operaciones-backend
    python scripts/actualizar_proyectos_solares.py [--dry-run]
"""
import sys
import os
import re
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.proyectos import Proyecto, ProyectoInfoTecnica

DRY_RUN = "--dry-run" in sys.argv

# -- Operadores de Red ----------------------------------------------------------
OR_MAP = {
    "Perija":             "Afinia",
    "El son":             "Afinia",
    "Molino":             "Air-e",
    "Puya":               "Afinia",
    "Villanueva":         "Air-e",
    "Reserva":            "ESSA",
    "Cañahuate":          "Afinia",
    "La Paz Leyenda":     "Afinia",
    "La Paz Verso":       "Afinia",
    "San Pedro":          "Afinia",
    "La Paz Vallenata":   "Afinia",
    "Gandalf":            "Afinia",
    "Uruaco":             "Air-e",
    "Baraya":             "Afinia",
    "Esmeralda":          "Afinia",
    "El merengue":        "Afinia",
    "El Olimpo":          "ESSA",
    "Ibirico":            "Afinia",
    "La Mesa":            "ESSA",
    "San Diego Sur":      "Afinia",
    "La Cacica 2":        "Afinia",
    "La Molina":          "Afinia",
    "La Cumbia":          "Afinia",
    "Valencia 1":         "Afinia",
    "Valencia 2":         "Afinia",
}

# -- Mapa explícito nombre_topico -> keyword de búsqueda en DB ------------------
# Para proyectos cuyo nombre en el JSON no coincide con nombre_comercial en DB.
NOMBRE_MAP = {
    "MGS 0004 Valle de Gandalf":    "Gandalf",
    "MGS 0005 Cañahuate":           "Cañahuate",
    "MGS 0006 Perijá":              "Perija",
    "MGS 0007 La Paz Vallenata":    "La Paz Vallenata",
    "MGS 0008 La Paz Verso":        "La Paz Verso",
    "MGS 0009 El Molino":           "Molino",
    "MGS 0010 - Villanueva":        "Villanueva",
    "MGS 0011 El Roble":            "El Roble",
    "MGS 0013 La Mesa":             "La Mesa",
    "MGS 0014 - El Olimpo":         "El Olimpo",
    "MGS 0016 - Puya":              "Puya",
    "MGS 0017- Esmeralda":          "Esmeralda",
    "MGS 0018 La Paz Leyenda":      "La Paz Leyenda",
    "MGS 0019 El Merengue":         "merengue",
    "Complejo Industrial Cedillanos": "Cedillanos",
    "GRANJA SOLAR SAN AGUSTIN":     "San Agustin",
    "IML":                          "IML",
    "Los Coches":                   "Los Coches",
}

# -- helpers --------------------------------------------------------------------

def find_proj(db, keyword: str):
    kw = keyword.strip()
    # 1. Exacto
    r = db.query(Proyecto).filter(Proyecto.nombre_comercial == kw).first()
    if r:
        return r
    # 2. ilike nombre_comercial
    r = db.query(Proyecto).filter(Proyecto.nombre_comercial.ilike(f"%{kw}%")).first()
    if r:
        return r
    # 3. ilike nombre_bitacora
    r = db.query(Proyecto).filter(Proyecto.nombre_bitacora.ilike(f"%{kw}%")).first()
    if r:
        return r
    return None


def resolve_keyword(nombre_topico: str) -> str:
    """Devuelve el keyword de búsqueda: usa NOMBRE_MAP si existe,
    si no intenta quitar prefijo 'MGS XXXX' y retorna el resto."""
    if nombre_topico in NOMBRE_MAP:
        return NOMBRE_MAP[nombre_topico]
    # Quitar prefijo tipo "MGS 0009 ", "MGS 0014 - "
    stripped = re.sub(r"^MGS\s*\d+\s*[-\s]*", "", nombre_topico, flags=re.IGNORECASE).strip()
    return stripped if stripped else nombre_topico


def clean_dpto(s: str) -> str:
    """Limpia 'Sucre Department' -> 'Sucre', 'Bogota D.C.' queda igual."""
    return re.sub(r"\s+[Dd]epartment$", "", s.strip()).strip()


def upsert_info_tecnica(db, proyecto_id: int, paneles: int):
    it = db.query(ProyectoInfoTecnica).filter(
        ProyectoInfoTecnica.proyecto_id == proyecto_id
    ).first()
    if it:
        it.cantidad_total_paneles = paneles
    else:
        it = ProyectoInfoTecnica(
            proyecto_id=proyecto_id,
            cantidad_total_paneles=paneles,
        )
        db.add(it)


# -- main -----------------------------------------------------------------------

def main():
    db = SessionLocal()
    try:
        json_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "proyectos_solares_completo.json",
        )
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Procesando {len(data)} entradas JSON + {len(OR_MAP)} OR...\n")

        # -- Paso 1: actualizar desde JSON --------------------------------------
        print("PASO 1 -- Desde proyectos_solares_completo.json:\n")
        print(f"  {'Nombre JSON':<38} {'Proyecto DB':<28} Estado")
        print("  " + "-" * 78)

        json_updated = []
        json_notfound = []

        for row in data:
            nombre = row.get("nombre_topico", "").strip()
            kw = resolve_keyword(nombre)
            proj = find_proj(db, kw)

            if not proj:
                print(f"  {nombre:<38} {'- no encontrado -':<28} WARN SALTADO  (buscó: '{kw}')")
                json_notfound.append(nombre)
                continue

            changes = []

            dpto = clean_dpto(row.get("departamento") or "")
            if dpto and not proj.departamento:
                changes.append(f"depto={dpto!r}")
                if not DRY_RUN:
                    proj.departamento = dpto

            ciudad = (row.get("ciudad") or "").strip()
            if ciudad and not proj.municipio:
                changes.append(f"municipio={ciudad!r}")
                if not DRY_RUN:
                    proj.municipio = ciudad

            kwp = row.get("potencia_instalada_dc_kwp")
            if kwp is not None and not proj.potencia_instalada_kwp:
                changes.append(f"potencia={kwp}kWp")
                if not DRY_RUN:
                    proj.potencia_instalada_kwp = kwp

            paneles = row.get("numero_de_paneles")
            it_existente = db.query(ProyectoInfoTecnica).filter(
                ProyectoInfoTecnica.proyecto_id == proj.id
            ).first()
            if paneles is not None and not (it_existente and it_existente.cantidad_total_paneles):
                changes.append(f"paneles={paneles}")
                if not DRY_RUN:
                    upsert_info_tecnica(db, proj.id, paneles)

            if changes:
                json_updated.append(proj.nombre_comercial)
                estado = "OK " + ", ".join(changes)
            else:
                estado = "- ya completo"

            print(f"  {nombre:<38} {proj.nombre_comercial:<28} {estado}")

        # -- Paso 2: Operadores de Red ------------------------------------------
        print(f"\n  " + "-" * 78)
        print("\nPASO 2 -- Operadores de Red:\n")
        print(f"  {'Keyword':<25} {'Proyecto DB':<28} {'OR':<10} Estado")
        print("  " + "-" * 78)

        or_updated = []
        or_notfound = []

        for proj_kw, operador in OR_MAP.items():
            proj = find_proj(db, proj_kw)

            if not proj:
                print(f"  {proj_kw:<25} {'- no encontrado -':<28} {operador:<10} WARN SALTADO")
                or_notfound.append(proj_kw)
                continue

            if proj.operador_red and proj.operador_red.strip() == operador:
                estado = "- ya correcto"
            else:
                prev = proj.operador_red or "None"
                estado = f"OK {prev!r} -> {operador!r}"
                if not DRY_RUN:
                    proj.operador_red = operador
                or_updated.append(proj.nombre_comercial)

            print(f"  {proj_kw:<25} {proj.nombre_comercial:<28} {operador:<10} {estado}")

        # -- Commit y resumen ---------------------------------------------------
        if not DRY_RUN:
            db.commit()

        print(f"\n  " + "-" * 78)
        if DRY_RUN:
            print(f"\n[DRY-RUN] Se actualizarían:")
            print(f"  JSON -> {len(json_updated)} proyecto(s): {json_updated}")
            print(f"  OR   -> {len(or_updated)} proyecto(s): {or_updated}")
        else:
            print(f"\nOK Completado:")
            print(f"  JSON -> {len(json_updated)} proyecto(s) actualizados")
            print(f"  OR   -> {len(or_updated)} proyecto(s) actualizados")

        if json_notfound:
            print(f"\n  WARN No encontrados (JSON): {json_notfound}")
        if or_notfound:
            print(f"  WARN No encontrados (OR):   {or_notfound}")

    except Exception:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
