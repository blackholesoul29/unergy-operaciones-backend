"""
Script de carga masiva con UPSERT: clientes + proyectos + inversionistas.
Clientes:      upsert por nit_cedula (PATCH si ya existe, POST si es nuevo).
Proyectos:     upsert por topic_slug  (PATCH si ya existe, POST si es nuevo).
Inversionistas: insert-if-not-exists por par (proyecto_id, cliente_id).
"""
import requests

BASE = "https://backend-production-63d8.up.railway.app"


def get_token():
    r = requests.post(f"{BASE}/api/v1/auth/token",
        data={"username": "juanjose@unergy.io", "password": "Unergy2025!"}, timeout=30)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def fetch_all(endpoint, headers):
    """Obtiene todos los items de un endpoint paginado (max size=100 por pagina)."""
    items = []
    page = 1
    while True:
        r = requests.get(f"{BASE}{endpoint}?page={page}&size=100", headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        items.extend(data["items"])
        if len(items) >= data["total"]:
            break
        page += 1
    return items


def post_or_patch(method, url, payload, headers):
    fn = requests.post if method == "POST" else requests.patch
    r = fn(url, json=payload, headers=headers, timeout=30)
    if r.status_code == 401:
        headers.update(get_token())
        r = fn(url, json=payload, headers=headers, timeout=30)
    return r


# ── 1. CLIENTES PENDIENTES ────────────────────────────────────────────────────

CLIENTES_PENDIENTES = [
    {"razon_social_nombre": "INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C", "nit_cedula": "900.948.954-5", "ciudad": "Santander"},
    {"razon_social_nombre": "RODRIGUEZ VELEZ BEATRIZ",                    "nit_cedula": "32.443.784-3",  "ciudad": "Envigado"},
    {"razon_social_nombre": "SUN CAPITAL S.A.S",                          "nit_cedula": "901.605.102-9", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "PARQUE EOLICO DE GALERAZAMBA S.A.S.",        "nit_cedula": "901.049.630-0", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "SUNO ACTIVOS SOSTENIBLES S.A.S.",            "nit_cedula": "901.372.693-8", "ciudad": "Medellin"},
    {"razon_social_nombre": "NOVAVALOR ENERGY SAS",                       "nit_cedula": "901.029.373-7", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "GRANJAS SOLARES DELTA S.A.S. E.S.P",        "nit_cedula": "901.822.561-6", "ciudad": "Medellin"},
    {"razon_social_nombre": "GRANJA SOLAR POLARIS ENERGY S.A.S.",         "nit_cedula": "901.801.262-9", "ciudad": "Narino"},
    {"razon_social_nombre": "GRANJA SOLAR POLARIS 2 S.A.S.",              "nit_cedula": "901.862.384-1", "ciudad": "Narino"},
    {"razon_social_nombre": "FONSAR S.A.S.",                              "nit_cedula": "901.497.656-2", "ciudad": "Santander"},
    {"razon_social_nombre": "LA HORMIGA SOLAR S.A.S. E.S.P.",            "nit_cedula": "901.704.417-8", "ciudad": "Barranquilla"},
    {"razon_social_nombre": "ENEXA ENERGY S.A.S",                         "nit_cedula": "901.420.530-2", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "FEM ENERGIA S.A.S.",                         "nit_cedula": "901.683.197-0", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "PELLETCO S.A.S.",                            "nit_cedula": "900.948.147-8", "ciudad": "Floridablanca"},
    {"razon_social_nombre": "QUANTUM ENERGY INGENIERIA S.A.S.",           "nit_cedula": "900.936.846-6", "ciudad": "Cucuta"},
    {"razon_social_nombre": "INENERGY S.A.S.",                            "nit_cedula": "900.899.077-1", "ciudad": "Monteria"},
    {"razon_social_nombre": "ENERGY INVESTMENT GROUP SAS",                "nit_cedula": "900.623.254-2", "ciudad": "Cucuta"},
    {"razon_social_nombre": "INVERSIONES BIOSOSTENIBLES S.A.S.",          "nit_cedula": "901.364.683-0", "ciudad": "Cucuta"},
    {"razon_social_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "nit_cedula": "830.054.539-1", "ciudad": "Medellin"},
    {"razon_social_nombre": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.", "nit_cedula": "830.057.062-3", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "SAMBA SOLAR S.A.S.",                         "nit_cedula": "901.835.236-3", "ciudad": "Barranquilla"},
]

# ── 2. PROYECTOS ──────────────────────────────────────────────────────────────
# tipo_tecnologia: "solar" por defecto; indicar explicitamente si es diferente

PROYECTOS_RAW = [
    {"topic_slug": "mgs0012lareserva",   "nombre_comercial": "Minigranja Solar La Palma",            "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.38, "cliente_nombre": "STRADA ASOCIADOS S A S"},
    {"topic_slug": "agustin_1",          "nombre_comercial": "GD Agustin 1",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "FONSAR S.A.S."},
    {"topic_slug": "astrolumen",         "nombre_comercial": "GD Astrolumen La Garita",               "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nombre": "ENERGY INVESTMENT GROUP SAS"},
    {"topic_slug": "baraya",             "nombre_comercial": "Minigranja Solar Baraya",               "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.97, "cliente_nombre": "SUNO ACTIVOS SOSTENIBLES S.A.S."},
    {"topic_slug": "bayunca",            "nombre_comercial": "Bayunca",                               "potencia_instalada_kwp": 3000, "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "PARQUE EOLICO DE GALERAZAMBA S.A.S."},
    {"topic_slug": "biosolar",           "nombre_comercial": "GD Biosolar",                          "potencia_instalada_kwp": 500,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nombre": "INVERSIONES BIOSOSTENIBLES S.A.S."},
    {"topic_slug": "bongos",             "nombre_comercial": "Sol Y Cielo 7 Los Bongos",              "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.89, "cliente_nombre": "INENERGY S.A.S."},
    {"topic_slug": "cacica",             "nombre_comercial": "MGS 0040 Cacica",                       "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nombre": "Ayurá S.A.S"},
    {"topic_slug": "catedral",           "nombre_comercial": "La Catedral",                           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 1872,  "produccion_especifica_kwh_kwp": 5.7,  "cliente_nombre": "PELLETCO S.A.S."},
    {"topic_slug": "canahuate",          "nombre_comercial": "MGS 0005 Canahuate",                    "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "cedillanosexc",      "nombre_comercial": "Cedillanos_excedentes",                 "potencia_instalada_kwp": 936,  "cantidad_total_paneles": 2176,  "produccion_especifica_kwh_kwp": 3.8,  "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "chima",              "nombre_comercial": "MGS 0030 Chima Oriente",                "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "chiriguana_norte_2", "nombre_comercial": "MGS 0075 - Chiriguana Norte 2",         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2023,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nombre": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A."},
    {"topic_slug": "chiriguana_norte_4", "nombre_comercial": "MGS 0077 - Chiriguana Norte 4",         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nombre": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A."},
    {"topic_slug": "cienaga",            "nombre_comercial": "Sol&Cielo 9 - Cienaga",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nombre": "INENERGY S.A.S."},
    {"topic_slug": "copey_occidente",    "nombre_comercial": "MGS 0025 - El Copey Occidente",         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "cumbia",             "nombre_comercial": "MGS 0022 - La Cumbia",                  "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.79, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "delta_1",            "nombre_comercial": "GD Delta 1",                            "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nombre": "GRANJAS SOLARES DELTA S.A.S. E.S.P"},
    {"topic_slug": "delta_2",            "nombre_comercial": "GD delta 2",                            "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "GRANJAS SOLARES DELTA S.A.S. E.S.P"},
    {"topic_slug": "elmolino",           "nombre_comercial": "MGS 0009 El Molino",                    "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.69, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "esmeralda",          "nombre_comercial": "MGS 0017- Esmeralda",                   "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 5.5,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "gandalf",            "nombre_comercial": "MGS 0004 Valle de Gandalf",             "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "ibirico",            "nombre_comercial": "MGS 0021 Ibirico",                      "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "SUN CAPITAL S.A.S"},
    {"topic_slug": "jerico_el_son",      "nombre_comercial": "Minigranja Solar El Son",               "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.99, "cliente_nombre": "SUNO ACTIVOS SOSTENIBLES S.A.S."},
    {"topic_slug": "jerico_merengue",    "nombre_comercial": "MGS 0019 El Merengue",                  "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.99, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "joropo",             "nombre_comercial": "MGS 0023 Joropo",                       "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "lamesa",             "nombre_comercial": "MGS 0013 La Mesa",                      "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.4,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "mapale",             "nombre_comercial": "MGS Mapale",                            "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "SUN CAPITAL S.A.S"},
    {"topic_slug": "marimonda",          "nombre_comercial": "GD Marimonda",                          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "LA HORMIGA SOLAR S.A.S. E.S.P."},
    {"topic_slug": "mgs0011",            "nombre_comercial": "MGS 0011 El Roble",                     "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 5.46, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "mgs18",              "nombre_comercial": "MGS 0018 La Paz Leyenda",               "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 5.76, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "naos1",              "nombre_comercial": "GD NAOS 1",                             "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2368,  "produccion_especifica_kwh_kwp": 4.6,  "cliente_nombre": "GD EL REMOLINO 1 S.A.S. E.S.P."},
    {"topic_slug": "naos2",              "nombre_comercial": "MGS Naos 2",                            "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2250,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "GD EL REMOLINO 1 S.A.S. E.S.P."},
    {"topic_slug": "naos3",              "nombre_comercial": "MGS Naos 3",                            "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2250,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "GD EL REMOLINO 1 S.A.S. E.S.P."},
    {"topic_slug": "olimpo",             "nombre_comercial": "MGS 0014 - El Olimpo",                  "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "perija",             "nombre_comercial": "MGS 0006 Perija",                       "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 5.4,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "piloneras",          "nombre_comercial": "MGS 0041 Piloneras",                    "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.8,  "cliente_nombre": "Ayurá S.A.S"},
    {"topic_slug": "polaris_1",          "nombre_comercial": "GD Polaris 1",                          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nombre": "GRANJA SOLAR POLARIS ENERGY S.A.S."},
    {"topic_slug": "polaris_2",          "nombre_comercial": "GD Polaris 2",                          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "GRANJA SOLAR POLARIS 2 S.A.S."},
    {"topic_slug": "puya",               "nombre_comercial": "MGS 0016 - Puya",                       "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.7,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "sabana_de_torres",   "nombre_comercial": "Minigranja Solar Sabana de Torres",     "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.65, "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "san_diego_sur",      "nombre_comercial": "MGS 0024 - San Diego Sur",              "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": None, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "san_onofre",         "nombre_comercial": "GD 1MVA SAN ONOFRE",                    "potencia_instalada_kwp": 900,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nombre": "NOVAVALOR ENERGY SAS"},
    {"topic_slug": "san_pelayo",         "nombre_comercial": "GD San Pelayo",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 1980,  "produccion_especifica_kwh_kwp": 5.5,  "cliente_nombre": "SAMBA SOLAR S.A.S."},
    {"topic_slug": "sanpedro",           "nombre_comercial": "Minigranja Solar San Pedro",            "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "sirius",             "nombre_comercial": "GD Sirius",                             "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2136,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nombre": "QUANTUM ENERGY INGENIERIA S.A.S."},
    {"topic_slug": "tamalacue",          "nombre_comercial": "Minigranja Solar Tamalacue",            "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.53, "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "tierraalta",         "nombre_comercial": "Granja Solar Tierra Alta",              "potencia_instalada_kwp": 999,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.7,  "cliente_nombre": "UNERGY S.A.S"},
    {"topic_slug": "uruaco_gd",          "nombre_comercial": "Minigranja Solar Uruaco",               "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.4,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "valencia_oriente_2", "nombre_comercial": "MGS 0027 Valencia Oriente 2",           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "valenciaoriente",    "nombre_comercial": "MGS 0026 Valencia Oriente 1",           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA"},
    {"topic_slug": "vallenata",          "nombre_comercial": "MGS 0007 La Paz Vallenata",             "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.6,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "verso",              "nombre_comercial": "MGS 0008 La Paz Verso",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 5.6,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "villanueva",         "nombre_comercial": "MGS 0010 - Villanueva",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA"},
    {"topic_slug": "yuan_solar",         "nombre_comercial": "GD Yuan Solar",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2016,  "produccion_especifica_kwh_kwp": 4.04, "cliente_nombre": "FEM ENERGIA S.A.S."},
    {"topic_slug": "yurbaqua",           "nombre_comercial": "PSF - Yurbaqua",                        "potencia_instalada_kwp": 900,  "cantidad_total_paneles": 2352,  "produccion_especifica_kwh_kwp": 4.3,  "cliente_nombre": "ENEXA ENERGY S.A.S"},
]

# ── 3. INVERSIONISTAS POR PROYECTO ────────────────────────────────────────────
# pct: porcentaje en decimal (ej: 77.19% -> 0.7719)

INVERSIONISTAS = [
    {"proyecto": "Minigranja Solar Uruaco",        "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 0.771934},
    {"proyecto": "Minigranja Solar Uruaco",        "cliente": "SUNO ACTIVOS SOSTENIBLES S.A.S.",                                                              "pct": 0.117502},
    {"proyecto": "Minigranja Solar Uruaco",        "cliente": "RODRIGUEZ VELEZ BEATRIZ",                                                                      "pct": 0.110564},
    {"proyecto": "MGS 0005 Canahuate",             "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0004 Valle de Gandalf",      "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0006 Perija",                "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0007 La Paz Vallenata",      "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0009 El Molino",             "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0008 La Paz Verso",          "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0017- Esmeralda",            "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0010 - Villanueva",          "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0016 - Puya",                "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0014 - El Olimpo",           "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "MGS 0013 La Mesa",               "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
    {"proyecto": "Minigranja Solar Baraya",        "cliente": "SOMOS BOGOTÁ USME SAS",                                                                        "pct": 0.260049},
    {"proyecto": "Minigranja Solar Baraya",        "cliente": "Solenium S.A.S",                                                                               "pct": 0.122751},
    {"proyecto": "Minigranja Solar Baraya",        "cliente": "SUNO ACTIVOS SOSTENIBLES S.A.S.",                                                              "pct": 0.6172},
    {"proyecto": "Minigranja Solar El Son",        "cliente": "Solenium S.A.S",                                                                               "pct": 0.218743},
    {"proyecto": "Minigranja Solar El Son",        "cliente": "SUNO ACTIVOS SOSTENIBLES S.A.S.",                                                              "pct": 0.531257},
    {"proyecto": "Minigranja Solar El Son",        "cliente": "NACIONAL DE TRANSFORMADORES S.A.S",                                                            "pct": 0.25},
    {"proyecto": "MGS 0021 Ibirico",               "cliente": "SUN CAPITAL S.A.S",                                                                            "pct": 1.0},
    {"proyecto": "MGS Mapale",                     "cliente": "SUN CAPITAL S.A.S",                                                                            "pct": 1.0},
    {"proyecto": "MGS 0018 La Paz Leyenda",        "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "Minigranja Solar La Palma",      "cliente": "STRADA ASOCIADOS S A S",                                                                       "pct": 0.1183},
    {"proyecto": "Minigranja Solar La Palma",      "cliente": "INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C",                                                   "pct": 0.6317},
    {"proyecto": "Minigranja Solar La Palma",      "cliente": "SUNO ACTIVOS SOSTENIBLES S.A.S.",                                                              "pct": 0.25},
    {"proyecto": "MGS 0024 - San Diego Sur",       "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0019 El Merengue",           "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0026 Valencia Oriente 1",    "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0027 Valencia Oriente 2",    "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0040 Cacica",                "cliente": "Ayurá S.A.S",                                                                                  "pct": 0.5},
    {"proyecto": "MGS 0040 Cacica",                "cliente": "Solenium S.A.S",                                                                               "pct": 0.5},
    {"proyecto": "MGS 0041 Piloneras",             "cliente": "Ayurá S.A.S",                                                                                  "pct": 0.5},
    {"proyecto": "MGS 0041 Piloneras",             "cliente": "Solenium S.A.S",                                                                               "pct": 0.5},
    {"proyecto": "MGS 0022 - La Cumbia",           "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0025 - El Copey Occidente",  "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA", "pct": 1.0},
    {"proyecto": "MGS 0075 - Chiriguana Norte 2",  "cliente": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",                                       "pct": 1.0},
    {"proyecto": "MGS 0077 - Chiriguana Norte 4",  "cliente": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",                                       "pct": 1.0},
    {"proyecto": "GD NAOS 1",                      "cliente": "GD EL REMOLINO 1 S.A.S. E.S.P.",                                                               "pct": 1.0},
    {"proyecto": "MGS Naos 2",                     "cliente": "GD EL REMOLINO 1 S.A.S. E.S.P.",                                                               "pct": 1.0},
    {"proyecto": "MGS Naos 3",                     "cliente": "GD EL REMOLINO 1 S.A.S. E.S.P.",                                                               "pct": 1.0},
    {"proyecto": "GD 1MVA SAN ONOFRE",             "cliente": "NOVAVALOR ENERGY SAS",                                                                         "pct": 1.0},
    {"proyecto": "GD Delta 1",                     "cliente": "GRANJAS SOLARES DELTA S.A.S. E.S.P",                                                           "pct": 1.0},
    {"proyecto": "GD Polaris 1",                   "cliente": "GRANJA SOLAR POLARIS ENERGY S.A.S.",                                                           "pct": 1.0},
    {"proyecto": "GD Polaris 2",                   "cliente": "GRANJA SOLAR POLARIS 2 S.A.S.",                                                                "pct": 1.0},
    {"proyecto": "Bayunca",                        "cliente": "PARQUE EOLICO DE GALERAZAMBA S.A.S.",                                                          "pct": 1.0},
    {"proyecto": "GD Marimonda",                   "cliente": "LA HORMIGA SOLAR S.A.S. E.S.P.",                                                               "pct": 1.0},
    {"proyecto": "GD Agustin 1",                   "cliente": "FONSAR S.A.S.",                                                                                "pct": 1.0},
    {"proyecto": "PSF - Yurbaqua",                 "cliente": "ENEXA ENERGY S.A.S",                                                                           "pct": 1.0},
    {"proyecto": "GD Yuan Solar",                  "cliente": "FEM ENERGIA S.A.S.",                                                                           "pct": 1.0},
    {"proyecto": "La Catedral",                    "cliente": "PELLETCO S.A.S.",                                                                              "pct": 1.0},
    {"proyecto": "GD Sirius",                      "cliente": "QUANTUM ENERGY INGENIERIA S.A.S.",                                                             "pct": 1.0},
    {"proyecto": "Sol Y Cielo 7 Los Bongos",       "cliente": "INENERGY S.A.S.",                                                                              "pct": 1.0},
    {"proyecto": "GD Astrolumen La Garita",        "cliente": "ENERGY INVESTMENT GROUP SAS",                                                                  "pct": 1.0},
    {"proyecto": "GD Biosolar",                    "cliente": "INVERSIONES BIOSOSTENIBLES S.A.S.",                                                            "pct": 1.0},
    {"proyecto": "Sol&Cielo 9 - Cienaga",          "cliente": "INENERGY S.A.S.",                                                                              "pct": 1.0},
    {"proyecto": "GD San Pelayo",                  "cliente": "SAMBA SOLAR S.A.S.",                                                                           "pct": 1.0},
    {"proyecto": "MGS 0011 El Roble",              "cliente": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                         "pct": 1.0},
]


# ── EJECUCION ─────────────────────────────────────────────────────────────────

def main():
    print("Autenticando...")
    h = get_token()

    # ── Pre-carga: leer BD completa ANTES de modificar nada ──────────────────
    print("\nLeyendo estado actual de la BD...")

    existing_clientes = fetch_all("/api/v1/clientes", h)
    clientes_by_nit  = {c["nit_cedula"]: c for c in existing_clientes if c.get("nit_cedula")}
    clientes_map     = {c["razon_social_nombre"].strip(): c["id"] for c in existing_clientes}
    print(f"  {len(existing_clientes)} clientes en BD")

    existing_proyectos = fetch_all("/api/v1/proyectos", h)
    proyectos_by_slug  = {p["topic_slug"]: p for p in existing_proyectos if p.get("topic_slug")}
    proyectos_map      = {p["nombre_comercial"].strip(): p["id"] for p in existing_proyectos}

    # Construir set de pares (proyecto_id, cliente_id) ya existentes
    existing_investors: set[tuple[int, int]] = set()
    for p in existing_proyectos:
        for inv in p.get("inversionistas", []):
            existing_investors.add((p["id"], inv["cliente_id"]))
    print(f"  {len(existing_proyectos)} proyectos en BD")
    print(f"  {len(existing_investors)} relaciones inversionista en BD")

    unergy_id = clientes_map.get("UNERGY S.A.S")
    if not unergy_id:
        print("  ADVERTENCIA: UNERGY S.A.S no encontrado; proyectos sin cliente conocido se omitirán")

    # ── 1. Clientes: upsert por nit_cedula ───────────────────────────────────
    print("\n--- CLIENTES (UPSERT) ---")
    ok_new = ok_upd = err = 0
    for c in CLIENTES_PENDIENTES:
        existing = clientes_by_nit.get(c["nit_cedula"])
        if existing:
            r = post_or_patch("PATCH", f"{BASE}/api/v1/clientes/{existing['id']}", c, h)
            if r.status_code in (200, 201):
                ok_upd += 1
                clientes_map[c["razon_social_nombre"].strip()] = existing["id"]
                print(f"  UPD {c['razon_social_nombre']}")
            else:
                err += 1
                print(f"  ERR PATCH {c['razon_social_nombre']} - {r.status_code}: {r.text[:200]}")
        else:
            r = post_or_patch("POST", f"{BASE}/api/v1/clientes", c, h)
            if r.status_code in (200, 201):
                ok_new += 1
                new_id = r.json()["id"]
                clientes_map[c["razon_social_nombre"].strip()] = new_id
                clientes_by_nit[c["nit_cedula"]] = {**c, "id": new_id}
                print(f"  NEW {c['razon_social_nombre']}")
            else:
                err += 1
                print(f"  ERR POST {c['razon_social_nombre']} - {r.status_code}: {r.text[:200]}")
    print(f"Clientes: {ok_new} nuevos, {ok_upd} actualizados, {err} errores")

    # ── 2. Proyectos: upsert por topic_slug ──────────────────────────────────
    print("\n--- PROYECTOS (UPSERT) ---")
    ok_new = ok_upd = err = 0
    for p in PROYECTOS_RAW:
        cliente_id = clientes_map.get(p["cliente_nombre"], unergy_id)
        if not cliente_id:
            print(f"  SKIP {p['nombre_comercial']}: cliente '{p['cliente_nombre']}' no está en BD")
            err += 1
            continue

        payload = {
            "nombre_comercial":             p["nombre_comercial"],
            "topic_slug":                   p["topic_slug"],
            "cliente_id":                   cliente_id,
            "tipo_tecnologia":              p.get("tipo_tecnologia", "solar"),
            "potencia_instalada_kwp":       p["potencia_instalada_kwp"],
            "cantidad_total_paneles":       p["cantidad_total_paneles"],
            "produccion_especifica_kwh_kwp": p["produccion_especifica_kwh_kwp"],
        }

        existing = proyectos_by_slug.get(p["topic_slug"])
        if existing:
            r = post_or_patch("PATCH", f"{BASE}/api/v1/proyectos/{existing['id']}", payload, h)
            if r.status_code in (200, 201):
                ok_upd += 1
                proyectos_map[p["nombre_comercial"].strip()] = existing["id"]
                print(f"  UPD {p['nombre_comercial']}")
            else:
                err += 1
                print(f"  ERR PATCH {p['nombre_comercial']} - {r.status_code}: {r.text[:200]}")
        else:
            r = post_or_patch("POST", f"{BASE}/api/v1/proyectos", payload, h)
            if r.status_code in (200, 201):
                ok_new += 1
                new_id = r.json()["id"]
                proyectos_map[p["nombre_comercial"].strip()] = new_id
                proyectos_by_slug[p["topic_slug"]] = {**payload, "id": new_id}
                print(f"  NEW {p['nombre_comercial']}")
            else:
                err += 1
                print(f"  ERR POST {p['nombre_comercial']} - {r.status_code}: {r.text[:200]}")
    print(f"Proyectos: {ok_new} nuevos, {ok_upd} actualizados, {err} errores")

    # ── 3. Inversionistas: insert-if-not-exists por (proyecto_id, cliente_id) ─
    print("\n--- INVERSIONISTAS (INSERT IF NOT EXISTS) ---")
    ok = skip = err = 0
    for inv in INVERSIONISTAS:
        proy_id = proyectos_map.get(inv["proyecto"])
        cli_id  = clientes_map.get(inv["cliente"].strip())

        if not proy_id:
            print(f"  SKIP proyecto '{inv['proyecto']}' no encontrado en BD")
            skip += 1
            continue
        if not cli_id:
            print(f"  SKIP cliente '{inv['cliente']}' no encontrado en BD")
            skip += 1
            continue
        if (proy_id, cli_id) in existing_investors:
            print(f"  --   YA EXISTE {inv['proyecto']} / {inv['cliente']}")
            skip += 1
            continue

        payload = {"cliente_id": cli_id, "porcentaje_participacion": inv["pct"]}
        r = post_or_patch("POST", f"{BASE}/api/v1/proyectos/{proy_id}/inversionistas", payload, h)
        if r.status_code in (200, 201):
            ok += 1
            existing_investors.add((proy_id, cli_id))
        else:
            err += 1
            print(f"  ERR {inv['proyecto']} / {inv['cliente']} - {r.status_code}: {r.text[:200]}")
    print(f"Inversionistas: {ok} nuevos, {skip} ya existian / sin cliente, {err} errores")

    print("\nCarga completa.")


if __name__ == "__main__":
    main()
