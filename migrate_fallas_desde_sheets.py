"""
Migración completa: Google Apps Script -> Plataforma Operaciones

Pasos que ejecuta:
  1. Crea proyectos faltantes en la plataforma (idempotente)
  2. Descarga fallas desde Apps Script
  3. Inserta cada falla en PostgreSQL (idempotente via codigo_legado)
  4. Crea seguimiento inicial con datos históricos

Uso:
    python migrate_fallas_desde_sheets.py [--dry-run]

Requiere:
    pip install requests
"""
import sys
import json
import time
import unicodedata
import re
import argparse
from datetime import datetime, date
from typing import Optional

import requests

# -- Configuración --------------------------------------------------------------
SCRIPT_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbyJCkBZuLJxsJrMNnu1vsGUw3SX1Npqws1t3B2BN612GV0Nfn67TkT-Nl77wg11w1ST/exec"
)
API_BASE  = "https://backend-production-63d8.up.railway.app/api/v1"
API_EMAIL = "juanjose@unergy.io"
API_PASS  = "Unergy2025!"

# Cliente por defecto para proyectos históricos (UNERGY S.A.S, id=26)
DEFAULT_CLIENTE_ID = 26

# -- Mapeo manual confirmado: nombre antiguo -> proyecto_id en plataforma --------
PROYECTO_MAP: dict[str, int] = {
    "Cañahuate":             10,   # MGS 0005 Canahuate
    "Uruaco":                49,   # Minigranja Solar Uruaco
    "El Merengue":           25,   # MGS 0019 El Merengue
    "La Paz Esmeralda":      21,   # MGS 0017- Esmeralda
    "Gandalf":               22,   # MGS 0004 Valle de Gandalf
    "La Paz Leyenda":        31,   # MGS 0018 La Paz Leyenda
    "La Paz Vallenata":      52,   # MGS 0007 La Paz Vallenata
    "Pilonera":              37,   # MGS 0041 Piloneras
    "Molino":                20,   # MGS 0009 El Molino
    "La Paz Verso":          53,   # MGS 0008 La Paz Verso
    "El Olimpo":             35,   # MGS 0014 - El Olimpo
    "La Mesa":               27,   # MGS 0013 La Mesa
    "Perija":                36,   # MGS 0006 Perija
    "San Diego Sur":         42,   # MGS 0024 - San Diego Sur
    "Villanueva":            54,   # MGS 0010 - Villanueva
    "La Puya":               40,   # MGS 0016 - Puya
    "Cacica":                 8,   # MGS 0040 Cacica
    "Baraya":                 4,   # Minigranja Solar Baraya
    "San Pedro":             45,   # Minigranja Solar San Pedro
    "Copey":                 16,   # MGS 0025 - El Copey Occidente
    "Ibirico":               23,   # MGS 0021 Ibirico
    "Cumbia":                17,   # MGS 0022 - La Cumbia
    "El Son":                24,   # Minigranja Solar El Son
    "Chiriguana N°2":        13,   # MGS 0075 - Chiriguana Norte 2
    "Chiriguana N°4":        14,   # MGS 0077 - Chiriguana Norte 4
    "Valencia 1":            51,   # MGS 0026 Valencia Oriente 1
    "Valencia 2":            50,   # MGS 0027 Valencia Oriente 2
}

# Proyectos a crear si no existen (nombre antiguo -> nombre_comercial en plataforma)
PROYECTOS_CREAR = [
    "Cedillanos",
    "La Reserva",
    "Nestlé",
    "Maderas",
    "Salud Vegas",
    "IML Empaques",
    "Los Coches",
    "Acanto",
    "Laureles Parques",
    "AMC",
    "Nuevo Gimnasio School",
    "Almagran",
    "Seridme",
    "Cross",
    "Coopsana Sub Proyecto 1",
    "Pola del Pub",
    "MDM",
    "San Simón",
    "Ecoimagen",
    "IBES",
    "Polikem",
    "San Angelo",
    "Cristo Rey",
    "Laureles Fuentes Torre 3",
    "San Esteban Torre 1",
    "Somer Torre 1",
    "Somer Torre 2",
]

# -- Mapeo de estados (etiqueta antigua -> código nuevo) -------------------------
ESTADO_MAP = {
    "activa":      "abierta",
    "revision":    "en_gestion",
    "programada":  "en_espera",
    "terminada":   "cerrada",
    "Activa":      "abierta",
    "En Revisión": "en_gestion",
    "En Revision": "en_gestion",
    "Programada":  "en_espera",
    "Terminada":   "cerrada",
}

# Mapeo prioridad (texto libre -> código)
PRIO_MAP = {
    "alta":    "critica",
    "media":   "media",
    "baja":    "leve",
    "crítica": "critica",
    "critica": "critica",
    "grave":   "grave",
}

# Mapeo resolución (texto libre -> código catálogo)
RESOLUCION_KEYWORDS = [
    (["reinicio", "reset", "inversor"],          "reinicio_inversor"),
    (["visita", "técnica", "tecnica"],           "visita_tecnica"),
    (["cambio", "componente", "reemplazo"],      "cambio_componente"),
    (["firmware", "actualización", "software"],  "actualizacion_fw"),
    (["operador", "red", "empresa", "intervenc"],"intervencion_red"),
    (["remota", "telegestión", "telemando"],     "resolucion_remota"),
    (["sin acción", "no aplica", "sin accion"],  "sin_accion"),
]

# Mapeo tipo de falla: prefijo del código antiguo -> código de categoría nueva
CATEGORIA_PREFIJO = {
    "1": "medicion",    # Fallas de Medición
    "2": "inversor",    # Fallas Eléctricas / Inversores
    "3": "otro",        # Eventos Adversos
    "4": "produccion",  # Desgaste / Degradación
    "5": "red",         # Civiles / Estructurales / Red
}

# -- Helpers --------------------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.lower().strip())


def parse_date(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    raw_date = raw.strip().split(" ")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw_date, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_datetime(raw: str) -> Optional[str]:
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            pass
    return None


# -- Autenticación --------------------------------------------------------------

def get_token() -> str:
    r = requests.post(f"{API_BASE}/auth/token",
                      data={"username": API_EMAIL, "password": API_PASS})
    r.raise_for_status()
    return r.json()["access_token"]


def hdrs(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# -- Catálogos ------------------------------------------------------------------

def cargar_catalogos(token: str) -> dict:
    r = requests.get(f"{API_BASE}/fallas/catalogos", headers=hdrs(token))
    r.raise_for_status()
    return r.json()


def cargar_proyectos(token: str) -> dict[str, int]:
    """Devuelve {nombre_comercial: id}"""
    r = requests.get(f"{API_BASE}/proyectos", headers=hdrs(token), params={"size": 500})
    r.raise_for_status()
    return {p["nombre_comercial"]: p["id"] for p in r.json()["items"]}


# -- Crear proyectos faltantes --------------------------------------------------

def asegurar_proyectos(token: str, dry_run: bool) -> dict[str, int]:
    """
    Garantiza que todos los proyectos de PROYECTOS_CREAR existen en la plataforma.
    Devuelve el mapa completo {nombre_antiguo: proyecto_id}.
    """
    existentes = cargar_proyectos(token)
    # nombre exacto -> id (para los ya mapeados en PROYECTO_MAP)
    mapa = dict(PROYECTO_MAP)

    creados = 0
    for nombre in PROYECTOS_CREAR:
        # buscar por nombre exacto o normalizado
        pid = existentes.get(nombre)
        if pid is None:
            # búsqueda normalizada
            for pnombre, pid_ex in existentes.items():
                if norm(pnombre) == norm(nombre):
                    pid = pid_ex
                    break

        if pid is not None:
            mapa[nombre] = pid
            print(f"  [EXISTE] '{nombre}' -> id={pid}")
        else:
            if dry_run:
                print(f"  [DRY] Crearía proyecto '{nombre}'")
                mapa[nombre] = -1
            else:
                payload = {
                    "nombre_comercial": nombre,
                    "cliente_id": DEFAULT_CLIENTE_ID,
                    "estado": "en_operacion",
                    "tipo_proyecto": "otro",
                    "tipo_tecnologia": "solar",
                }
                r = requests.post(f"{API_BASE}/proyectos", json=payload, headers=hdrs(token))
                if r.status_code == 201:
                    nuevo_id = r.json()["id"]
                    mapa[nombre] = nuevo_id
                    existentes[nombre] = nuevo_id
                    creados += 1
                    print(f"  [CREADO] '{nombre}' -> id={nuevo_id}")
                else:
                    print(f"  [ERROR] No se pudo crear '{nombre}': {r.status_code} {r.text[:100]}")

    if creados:
        print(f"\n  {creados} proyectos nuevos creados.")
    return mapa


# -- Mapeo de catálogos ---------------------------------------------------------

def map_estado(raw: str, estados: list) -> int:
    codigo = ESTADO_MAP.get(raw.strip(), "abierta")
    for e in estados:
        if e["codigo"] == codigo:
            return e["id"]
    return next(e["id"] for e in estados if e["codigo"] == "abierta")


def map_prioridad(raw: str, prioridades: list) -> int:
    codigo = PRIO_MAP.get(raw.strip().lower(), "media")
    for p in prioridades:
        if p["codigo"] == codigo:
            return p["id"]
    return next(p["id"] for p in sorted(prioridades, key=lambda x: x["nivel"]) if p["nivel"] == 3)


def map_resolucion(raw: str, resoluciones: list) -> Optional[int]:
    if not raw or not raw.strip():
        return None
    r_norm = norm(raw)
    for keywords, codigo in RESOLUCION_KEYWORDS:
        if any(k in r_norm for k in keywords):
            for res in resoluciones:
                if res["codigo"] == codigo:
                    return res["id"]
    # fallback: "otro"
    for res in resoluciones:
        if res["codigo"] == "otro":
            return res["id"]
    return None


def map_tipo(fault_code: str, tipos: list) -> int:
    prefijo = str(fault_code).split(".")[0].strip()
    cat_hint = CATEGORIA_PREFIJO.get(prefijo, "otro")
    for t in tipos:
        cat_cod = (t.get("categoria") or {}).get("codigo", "")
        if cat_cod == cat_hint:
            return t["id"]
    for t in tipos:
        if t["codigo"] == "otro_general":
            return t["id"]
    return tipos[0]["id"]


# -- Descarga fallas ------------------------------------------------------------

def fetch_fallas() -> list:
    print("\nDescargando fallas desde Apps Script...")
    r = requests.get(SCRIPT_URL, params={"action": "getFaults"},
                     allow_redirects=True, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    data = r.json()
    if not data.get("ok") or not data.get("faults"):
        print(f"ERROR: respuesta inesperada: {r.text[:200]}")
        sys.exit(1)
    fallas = data["faults"]
    print(f"  {len(fallas)} fallas descargadas.")
    return fallas


# -- Verificar duplicado --------------------------------------------------------

def ya_existe(codigo_legado: str, token: str) -> bool:
    r = requests.get(f"{API_BASE}/fallas",
                     headers=hdrs(token),
                     params={"codigo_legado": codigo_legado, "size": 1})
    return r.ok and r.json().get("total", 0) > 0


# -- Migrar falla ---------------------------------------------------------------

def migrar_falla(raw: dict, proyecto_id: int, catalogos: dict,
                 token: str, dry_run: bool) -> bool:
    estados    = catalogos["estados"]
    prioridades = catalogos["prioridades"]
    tipos       = catalogos["tipos"]
    resoluciones = catalogos["resoluciones"]

    codigo_legado = str(raw.get("ID", "")).strip()
    if not codigo_legado:
        return False

    # Idempotencia: saltar si ya existe
    if not dry_run and ya_existe(codigo_legado, token):
        return False  # silencioso — ya migrado

    fecha_id = parse_date(str(raw.get("Fecha de Identificación", "")))
    if not fecha_id:
        fecha_id = date.today().isoformat()

    descripcion = " | ".join(filter(None, [
        str(raw.get("Descripción Falla", "")).strip(),
        str(raw.get("Descripción", "")).strip(),
    ])) or "Migrada desde sistema anterior"

    payload = {
        "proyecto_id":         proyecto_id,
        "tipo_id":             map_tipo(str(raw.get("Código de Falla", "")), tipos),
        "estado_id":           map_estado(str(raw.get("Estado", "activa")), estados),
        "prioridad_id":        map_prioridad(str(raw.get("Prioridad", "")), prioridades),
        "descripcion":         descripcion[:2000],
        "fecha_identificacion": fecha_id,
        "codigo_legado":       codigo_legado,
    }

    resolucion_id = map_resolucion(str(raw.get("Tipo Resolución", "")), resoluciones)
    if resolucion_id:
        payload["resolucion_id"] = resolucion_id

    fecha_occ = parse_datetime(str(raw.get("Fecha y Hora de Ocurrencia", "")))
    if fecha_occ:
        payload["fecha_ocurrencia"] = fecha_occ

    fecha_res = parse_datetime(str(raw.get("Fecha y Hora de Terminación", "")))
    if fecha_res:
        payload["fecha_resolucion"] = fecha_res

    hora_raw = str(raw.get("Hora de Identificación", "")).strip()
    if hora_raw and re.match(r"^\d{2}:\d{2}", hora_raw):
        payload["hora_identificacion"] = hora_raw[:5]

    if dry_run:
        return True

    r = requests.post(f"{API_BASE}/fallas", json=payload, headers=hdrs(token))
    if r.status_code != 201:
        print(f"    ERROR [{codigo_legado}] {r.status_code}: {r.text[:120]}")
        return False

    nueva_id = r.json()["id"]

    # Seguimiento con contexto histórico
    partes = [f"Migrado desde sistema anterior (ID original: {codigo_legado})"]
    cat_raw = str(raw.get("Categoría", "")).strip()
    cod_raw = str(raw.get("Código de Falla", "")).strip()
    if cat_raw or cod_raw:
        partes.append(f"Categoría/Código original: {cat_raw} — {cod_raw}")
    seguim = str(raw.get("Seguimiento", "")).strip()
    if seguim:
        partes.append(f"Seguimiento: {seguim}")
    centinela = str(raw.get("Centinela", "")).strip()
    if centinela:
        partes.append(f"Centinela: {centinela}")
    fotos = str(raw.get("Fotos (Enlace Drive)", "")).strip()
    if fotos:
        partes.append(f"Fotos: {fotos}")

    requests.post(
        f"{API_BASE}/fallas/{nueva_id}/seguimientos",
        json={"nota": "\n".join(partes)},
        headers=hdrs(token),
    )
    # pequeña pausa para no saturar Railway
    time.sleep(0.05)
    return True


# -- Main -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sin escribir nada en la BD")
    args = parser.parse_args()
    dry_run = args.dry_run

    print("=" * 65)
    print("  Migracion fallas-unergy -> Plataforma Operaciones Unergy")
    if dry_run:
        print("  MODO DRY-RUN — no se escribirá nada")
    print("=" * 65)

    token = get_token()
    print(f"Autenticado como {API_EMAIL}\n")

    # -- 1. Proyectos ----------------------------------------------
    print("-- Paso 1: Verificando / creando proyectos ------------------")
    proyecto_map = asegurar_proyectos(token, dry_run)

    # -- 2. Catálogos ----------------------------------------------
    print("\n-- Paso 2: Cargando catálogos de fallas ---------------------")
    catalogos = cargar_catalogos(token)
    print(f"  {len(catalogos['estados'])} estados | "
          f"{len(catalogos['prioridades'])} prioridades | "
          f"{len(catalogos['tipos'])} tipos | "
          f"{len(catalogos['resoluciones'])} resoluciones")

    # -- 3. Fallas desde Apps Script -------------------------------
    print("\n-- Paso 3: Descargando fallas -------------------------------")
    fallas_raw = fetch_fallas()

    # -- 4. Migración ----------------------------------------------
    print("\n-- Paso 4: Migrando fallas ----------------------------------")
    ok = skipped = sin_proyecto = ya_migrado = error = 0
    proyectos_sin_match: set[str] = set()

    for raw in fallas_raw:
        nombre_proj = str(raw.get("Proyecto", "")).strip()
        proyecto_id = proyecto_map.get(nombre_proj)

        if proyecto_id is None:
            sin_proyecto += 1
            proyectos_sin_match.add(nombre_proj)
            continue
        if proyecto_id == -1:  # dry-run placeholder
            ok += 1
            continue

        codigo_legado = str(raw.get("ID", "")).strip()
        if not dry_run and ya_existe(codigo_legado, token):
            ya_migrado += 1
            continue

        resultado = migrar_falla(raw, proyecto_id, catalogos, token, dry_run)
        if resultado:
            ok += 1
        else:
            error += 1

    # -- Reporte final ---------------------------------------------
    print("\n" + "=" * 65)
    print(f"  RESULTADO FINAL")
    print(f"  Migradas:        {ok}")
    print(f"  Ya existían:     {ya_migrado}")
    print(f"  Sin proyecto:    {sin_proyecto}")
    print(f"  Errores:         {error}")
    print(f"  Total procesado: {ok + ya_migrado + sin_proyecto + error}")
    if proyectos_sin_match:
        print(f"\n  Proyectos no encontrados:")
        for p in sorted(proyectos_sin_match):
            print(f"    * {p}")
    print("=" * 65)


if __name__ == "__main__":
    main()
