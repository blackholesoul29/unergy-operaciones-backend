"""
Carga masiva directa a BD via SQLAlchemy (sin HTTP).
Upsert clientes por nit_cedula, proyectos por topic_slug,
inversionistas por par (proyecto_id, cliente_id).

Uso:
    # Con la BD de Railway (obtener URL del dashboard):
    DATABASE_URL="postgresql+psycopg://..." python scripts/cargar_todo.py

    # Con la BD local:
    python scripts/cargar_todo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Permite sobreescribir DATABASE_URL desde entorno (ej: Railway)
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    from app.core.database import engine  # usa la config local (.env)

Session = sessionmaker(bind=engine)

from app.models.clientes import Cliente
from app.models.proyectos import Proyecto, ProyectoInversionista


# ── 1. CLIENTES ───────────────────────────────────────────────────────────────

CLIENTES = [
    {"razon_social_nombre": "UNERGY S.A.S",                                                                                    "nit_cedula": "901.224.596-0", "ciudad": "Medellin"},
    {"razon_social_nombre": "STRADA ASOCIADOS S A S",                                                                          "nit_cedula": "900.528.346-1", "ciudad": "Medellin"},
    {"razon_social_nombre": "Solenium S.A.S",                                                                                  "nit_cedula": "900.909.933-8", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "Ayurá S.A.S",                                                                                     "nit_cedula": "901.180.735-4", "ciudad": "Medellin"},
    {"razon_social_nombre": "GD EL REMOLINO 1 S.A.S. E.S.P.",                                                                  "nit_cedula": "901.481.652-5", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "SOMOS BOGOTÁ USME SAS",                                                                           "nit_cedula": "901.388.174-2", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "NACIONAL DE TRANSFORMADORES S.A.S",                                                               "nit_cedula": "890.919.397-4", "ciudad": "Medellin"},
    {"razon_social_nombre": "INVERSIONES ESTRADA ARBELAEZ Y CIA S. EN C",                                                      "nit_cedula": "900.948.954-5", "ciudad": "Santander"},
    {"razon_social_nombre": "RODRIGUEZ VELEZ BEATRIZ",                                                                         "nit_cedula": "32.443.784-3",  "ciudad": "Envigado"},
    {"razon_social_nombre": "SUN CAPITAL S.A.S",                                                                               "nit_cedula": "901.605.102-9", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "PARQUE EOLICO DE GALERAZAMBA S.A.S.",                                                             "nit_cedula": "901.049.630-0", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "SUNO ACTIVOS SOSTENIBLES S.A.S.",                                                                 "nit_cedula": "901.372.693-8", "ciudad": "Medellin"},
    {"razon_social_nombre": "NOVAVALOR ENERGY SAS",                                                                            "nit_cedula": "901.029.373-7", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "GRANJAS SOLARES DELTA S.A.S. E.S.P",                                                             "nit_cedula": "901.822.561-6", "ciudad": "Medellin"},
    {"razon_social_nombre": "GRANJA SOLAR POLARIS ENERGY S.A.S.",                                                              "nit_cedula": "901.801.262-9", "ciudad": "Narino"},
    {"razon_social_nombre": "GRANJA SOLAR POLARIS 2 S.A.S.",                                                                   "nit_cedula": "901.862.384-1", "ciudad": "Narino"},
    {"razon_social_nombre": "FONSAR S.A.S.",                                                                                   "nit_cedula": "901.497.656-2", "ciudad": "Santander"},
    {"razon_social_nombre": "LA HORMIGA SOLAR S.A.S. E.S.P.",                                                                  "nit_cedula": "901.704.417-8", "ciudad": "Barranquilla"},
    {"razon_social_nombre": "ENEXA ENERGY S.A.S",                                                                              "nit_cedula": "901.420.530-2", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "FEM ENERGIA S.A.S.",                                                                              "nit_cedula": "901.683.197-0", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "PELLETCO S.A.S.",                                                                                 "nit_cedula": "900.948.147-8", "ciudad": "Floridablanca"},
    {"razon_social_nombre": "QUANTUM ENERGY INGENIERIA S.A.S.",                                                                "nit_cedula": "900.936.846-6", "ciudad": "Cucuta"},
    {"razon_social_nombre": "INENERGY S.A.S.",                                                                                 "nit_cedula": "900.899.077-1", "ciudad": "Monteria"},
    {"razon_social_nombre": "ENERGY INVESTMENT GROUP SAS",                                                                     "nit_cedula": "900.623.254-2", "ciudad": "Cucuta"},
    {"razon_social_nombre": "INVERSIONES BIOSOSTENIBLES S.A.S.",                                                               "nit_cedula": "901.364.683-0", "ciudad": "Cucuta"},
    {"razon_social_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA - 17844 SOL DE LA SIERRA",   "nit_cedula": "830.054.539-1", "ciudad": "Medellin"},
    {"razon_social_nombre": "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA",                            "nit_cedula": "830.054.539-2", "ciudad": "Medellin"},
    {"razon_social_nombre": "PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",                                          "nit_cedula": "830.057.062-3", "ciudad": "Bogota, D.C"},
    {"razon_social_nombre": "SAMBA SOLAR S.A.S.",                                                                              "nit_cedula": "901.835.236-3", "ciudad": "Barranquilla"},
]


# ── 2. PROYECTOS ──────────────────────────────────────────────────────────────

PROYECTOS = [
    {"topic_slug": "mgs0012lareserva",   "nombre_comercial": "Minigranja Solar La Palma",           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.38, "cliente_nit": "900.528.346-1"},
    {"topic_slug": "agustin_1",          "nombre_comercial": "GD Agustin 1",                        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.497.656-2"},
    {"topic_slug": "astrolumen",         "nombre_comercial": "GD Astrolumen La Garita",              "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nit": "900.623.254-2"},
    {"topic_slug": "baraya",             "nombre_comercial": "Minigranja Solar Baraya",              "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.97, "cliente_nit": "901.372.693-8"},
    {"topic_slug": "bayunca",            "nombre_comercial": "Bayunca",                              "potencia_instalada_kwp": 3000, "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.049.630-0"},
    {"topic_slug": "biosolar",           "nombre_comercial": "GD Biosolar",                         "potencia_instalada_kwp": 500,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.364.683-0"},
    {"topic_slug": "bongos",             "nombre_comercial": "Sol Y Cielo 7 Los Bongos",             "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.89, "cliente_nit": "900.899.077-1"},
    {"topic_slug": "cacica",             "nombre_comercial": "MGS 0040 Cacica",                      "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nit": "901.180.735-4"},
    {"topic_slug": "catedral",           "nombre_comercial": "La Catedral",                          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 1872,  "produccion_especifica_kwh_kwp": 5.7,  "cliente_nit": "900.948.147-8"},
    {"topic_slug": "canahuate",          "nombre_comercial": "MGS 0005 Canahuate",                   "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nit": "830.054.539-2"},
    {"topic_slug": "cedillanosexc",      "nombre_comercial": "Cedillanos_excedentes",                "potencia_instalada_kwp": 936,  "cantidad_total_paneles": 2176,  "produccion_especifica_kwh_kwp": 3.8,  "cliente_nit": "901.224.596-0"},
    {"topic_slug": "chima",              "nombre_comercial": "MGS 0030 Chima Oriente",               "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.224.596-0"},
    {"topic_slug": "chiriguana_norte_2", "nombre_comercial": "MGS 0075 - Chiriguana Norte 2",        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2023,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nit": "830.057.062-3"},
    {"topic_slug": "chiriguana_norte_4", "nombre_comercial": "MGS 0077 - Chiriguana Norte 4",        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nit": "830.057.062-3"},
    {"topic_slug": "cienaga",            "nombre_comercial": "Sol&Cielo 9 - Cienaga",                "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 10000, "produccion_especifica_kwh_kwp": None, "cliente_nit": "900.899.077-1"},
    {"topic_slug": "copey_occidente",    "nombre_comercial": "MGS 0025 - El Copey Occidente",        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "cumbia",             "nombre_comercial": "MGS 0022 - La Cumbia",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.79, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "delta_1",            "nombre_comercial": "GD Delta 1",                           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.822.561-6"},
    {"topic_slug": "delta_2",            "nombre_comercial": "GD delta 2",                           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.822.561-6"},
    {"topic_slug": "elmolino",           "nombre_comercial": "MGS 0009 El Molino",                   "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.69, "cliente_nit": "830.054.539-2"},
    {"topic_slug": "esmeralda",          "nombre_comercial": "MGS 0017- Esmeralda",                  "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 5.5,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "gandalf",            "nombre_comercial": "MGS 0004 Valle de Gandalf",            "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nit": "830.054.539-2"},
    {"topic_slug": "ibirico",            "nombre_comercial": "MGS 0021 Ibirico",                     "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "901.605.102-9"},
    {"topic_slug": "jerico_el_son",      "nombre_comercial": "Minigranja Solar El Son",              "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.99, "cliente_nit": "901.372.693-8"},
    {"topic_slug": "jerico_merengue",    "nombre_comercial": "MGS 0019 El Merengue",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.99, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "joropo",             "nombre_comercial": "MGS 0023 Joropo",                      "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "901.224.596-0"},
    {"topic_slug": "lamesa",             "nombre_comercial": "MGS 0013 La Mesa",                     "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.4,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "mapale",             "nombre_comercial": "MGS Mapale",                           "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "901.605.102-9"},
    {"topic_slug": "marimonda",          "nombre_comercial": "GD Marimonda",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.704.417-8"},
    {"topic_slug": "mgs0011",            "nombre_comercial": "MGS 0011 El Roble",                    "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 5.46, "cliente_nit": "830.054.539-2"},
    {"topic_slug": "mgs18",              "nombre_comercial": "MGS 0018 La Paz Leyenda",              "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 5.76, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "naos1",              "nombre_comercial": "GD NAOS 1",                            "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2368,  "produccion_especifica_kwh_kwp": 4.6,  "cliente_nit": "901.481.652-5"},
    {"topic_slug": "naos2",              "nombre_comercial": "MGS Naos 2",                           "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2250,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "901.481.652-5"},
    {"topic_slug": "naos3",              "nombre_comercial": "MGS Naos 3",                           "potencia_instalada_kwp": 960,  "cantidad_total_paneles": 2250,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "901.481.652-5"},
    {"topic_slug": "olimpo",             "nombre_comercial": "MGS 0014 - El Olimpo",                 "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "830.054.539-2"},
    {"topic_slug": "perija",             "nombre_comercial": "MGS 0006 Perija",                      "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 5.4,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "piloneras",          "nombre_comercial": "MGS 0041 Piloneras",                   "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.8,  "cliente_nit": "901.180.735-4"},
    {"topic_slug": "polaris_1",          "nombre_comercial": "GD Polaris 1",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.801.262-9"},
    {"topic_slug": "polaris_2",          "nombre_comercial": "GD Polaris 2",                         "potencia_instalada_kwp": 990,  "cantidad_total_paneles": None,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.862.384-1"},
    {"topic_slug": "puya",               "nombre_comercial": "MGS 0016 - Puya",                      "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.7,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "sabana_de_torres",   "nombre_comercial": "Minigranja Solar Sabana de Torres",    "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2196,  "produccion_especifica_kwh_kwp": 4.65, "cliente_nit": "901.224.596-0"},
    {"topic_slug": "san_diego_sur",      "nombre_comercial": "MGS 0024 - San Diego Sur",             "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": None, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "san_onofre",         "nombre_comercial": "GD 1MVA SAN ONOFRE",                   "potencia_instalada_kwp": 900,  "cantidad_total_paneles": 100,   "produccion_especifica_kwh_kwp": None, "cliente_nit": "901.029.373-7"},
    {"topic_slug": "san_pelayo",         "nombre_comercial": "GD San Pelayo",                        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 1980,  "produccion_especifica_kwh_kwp": 5.5,  "cliente_nit": "901.835.236-3"},
    {"topic_slug": "sanpedro",           "nombre_comercial": "Minigranja Solar San Pedro",           "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.75, "cliente_nit": "901.224.596-0"},
    {"topic_slug": "sirius",             "nombre_comercial": "GD Sirius",                            "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2136,  "produccion_especifica_kwh_kwp": 5.9,  "cliente_nit": "900.936.846-6"},
    {"topic_slug": "tamalacue",          "nombre_comercial": "Minigranja Solar Tamalacue",           "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2280,  "produccion_especifica_kwh_kwp": 4.53, "cliente_nit": "901.224.596-0"},
    {"topic_slug": "tierraalta",         "nombre_comercial": "Granja Solar Tierra Alta",             "potencia_instalada_kwp": 999,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.7,  "cliente_nit": "901.224.596-0"},
    {"topic_slug": "uruaco_gd",          "nombre_comercial": "Minigranja Solar Uruaco",              "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2496,  "produccion_especifica_kwh_kwp": 4.4,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "valencia_oriente_2", "nombre_comercial": "MGS 0027 Valencia Oriente 2",          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "valenciaoriente",    "nombre_comercial": "MGS 0026 Valencia Oriente 1",          "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2032,  "produccion_especifica_kwh_kwp": 5.67, "cliente_nit": "830.054.539-1"},
    {"topic_slug": "vallenata",          "nombre_comercial": "MGS 0007 La Paz Vallenata",            "potencia_instalada_kwp": 996,  "cantidad_total_paneles": 2300,  "produccion_especifica_kwh_kwp": 4.6,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "verso",              "nombre_comercial": "MGS 0008 La Paz Verso",                "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 5.6,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "villanueva",         "nombre_comercial": "MGS 0010 - Villanueva",                "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2308,  "produccion_especifica_kwh_kwp": 4.5,  "cliente_nit": "830.054.539-2"},
    {"topic_slug": "yuan_solar",         "nombre_comercial": "GD Yuan Solar",                        "potencia_instalada_kwp": 990,  "cantidad_total_paneles": 2016,  "produccion_especifica_kwh_kwp": 4.04, "cliente_nit": "901.683.197-0"},
    {"topic_slug": "yurbaqua",           "nombre_comercial": "PSF - Yurbaqua",                       "potencia_instalada_kwp": 900,  "cantidad_total_paneles": 2352,  "produccion_especifica_kwh_kwp": 4.3,  "cliente_nit": "901.420.530-2"},
]


# ── 3. INVERSIONISTAS ─────────────────────────────────────────────────────────
# pct: porcentaje en decimal (ej: 77.19% → 0.7719)

INVERSIONISTAS = [
    {"slug": "uruaco_gd",          "nit": "830.054.539-2", "pct": 0.771934},
    {"slug": "uruaco_gd",          "nit": "901.372.693-8", "pct": 0.117502},
    {"slug": "uruaco_gd",          "nit": "32.443.784-3",  "pct": 0.110564},
    {"slug": "canahuate",          "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "gandalf",            "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "perija",             "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "vallenata",          "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "elmolino",           "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "verso",              "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "esmeralda",          "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "villanueva",         "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "puya",               "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "olimpo",             "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "lamesa",             "nit": "830.054.539-2", "pct": 1.0},
    {"slug": "baraya",             "nit": "901.388.174-2", "pct": 0.260049},
    {"slug": "baraya",             "nit": "900.909.933-8", "pct": 0.122751},
    {"slug": "baraya",             "nit": "901.372.693-8", "pct": 0.6172},
    {"slug": "jerico_el_son",      "nit": "900.909.933-8", "pct": 0.218743},
    {"slug": "jerico_el_son",      "nit": "901.372.693-8", "pct": 0.531257},
    {"slug": "jerico_el_son",      "nit": "890.919.397-4", "pct": 0.25},
    {"slug": "ibirico",            "nit": "901.605.102-9", "pct": 1.0},
    {"slug": "mapale",             "nit": "901.605.102-9", "pct": 1.0},
    {"slug": "mgs18",              "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "mgs0012lareserva",   "nit": "900.528.346-1", "pct": 0.1183},
    {"slug": "mgs0012lareserva",   "nit": "900.948.954-5", "pct": 0.6317},
    {"slug": "mgs0012lareserva",   "nit": "901.372.693-8", "pct": 0.25},
    {"slug": "san_diego_sur",      "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "jerico_merengue",    "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "valenciaoriente",    "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "valencia_oriente_2", "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "cacica",             "nit": "901.180.735-4", "pct": 0.5},
    {"slug": "cacica",             "nit": "900.909.933-8", "pct": 0.5},
    {"slug": "piloneras",          "nit": "901.180.735-4", "pct": 0.5},
    {"slug": "piloneras",          "nit": "900.909.933-8", "pct": 0.5},
    {"slug": "cumbia",             "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "copey_occidente",    "nit": "830.054.539-1", "pct": 1.0},
    {"slug": "chiriguana_norte_2", "nit": "830.057.062-3", "pct": 1.0},
    {"slug": "chiriguana_norte_4", "nit": "830.057.062-3", "pct": 1.0},
    {"slug": "naos1",              "nit": "901.481.652-5", "pct": 1.0},
    {"slug": "naos2",              "nit": "901.481.652-5", "pct": 1.0},
    {"slug": "naos3",              "nit": "901.481.652-5", "pct": 1.0},
    {"slug": "san_onofre",         "nit": "901.029.373-7", "pct": 1.0},
    {"slug": "delta_1",            "nit": "901.822.561-6", "pct": 1.0},
    {"slug": "polaris_1",          "nit": "901.801.262-9", "pct": 1.0},
    {"slug": "polaris_2",          "nit": "901.862.384-1", "pct": 1.0},
    {"slug": "bayunca",            "nit": "901.049.630-0", "pct": 1.0},
    {"slug": "marimonda",          "nit": "901.704.417-8", "pct": 1.0},
    {"slug": "agustin_1",          "nit": "901.497.656-2", "pct": 1.0},
    {"slug": "yurbaqua",           "nit": "901.420.530-2", "pct": 1.0},
    {"slug": "yuan_solar",         "nit": "901.683.197-0", "pct": 1.0},
    {"slug": "catedral",           "nit": "900.948.147-8", "pct": 1.0},
    {"slug": "sirius",             "nit": "900.936.846-6", "pct": 1.0},
    {"slug": "bongos",             "nit": "900.899.077-1", "pct": 1.0},
    {"slug": "astrolumen",         "nit": "900.623.254-2", "pct": 1.0},
    {"slug": "biosolar",           "nit": "901.364.683-0", "pct": 1.0},
    {"slug": "cienaga",            "nit": "900.899.077-1", "pct": 1.0},
    {"slug": "san_pelayo",         "nit": "901.835.236-3", "pct": 1.0},
    {"slug": "mgs0011",            "nit": "830.054.539-2", "pct": 1.0},
]


# ── EJECUCIÓN ─────────────────────────────────────────────────────────────────

def main():
    db = Session()
    try:
        # ── 1. Clientes ───────────────────────────────────────────────────────
        print("\n--- CLIENTES ---")
        clientes_by_nit: dict[str, int] = {}
        ok_new = ok_upd = 0

        for c in CLIENTES:
            nit = c["nit_cedula"]
            existing = db.query(Cliente).filter_by(nit_cedula=nit).first()
            if existing:
                existing.razon_social_nombre = c["razon_social_nombre"]
                existing.ciudad = c.get("ciudad")
                clientes_by_nit[nit] = existing.id
                ok_upd += 1
                print(f"  UPD {c['razon_social_nombre']}")
            else:
                nuevo = Cliente(
                    razon_social_nombre=c["razon_social_nombre"],
                    nit_cedula=nit,
                    ciudad=c.get("ciudad"),
                )
                db.add(nuevo)
                db.flush()  # obtiene el id sin commit
                clientes_by_nit[nit] = nuevo.id
                ok_new += 1
                print(f"  NEW {c['razon_social_nombre']}")

        db.commit()
        print(f"Clientes: {ok_new} nuevos, {ok_upd} actualizados")

        # ── 2. Proyectos ──────────────────────────────────────────────────────
        print("\n--- PROYECTOS ---")
        proyectos_by_slug: dict[str, int] = {}
        ok_new = ok_upd = err = 0

        for p in PROYECTOS:
            cliente_id = clientes_by_nit.get(p["cliente_nit"])
            if not cliente_id:
                print(f"  ERR {p['nombre_comercial']}: NIT {p['cliente_nit']} no encontrado")
                err += 1
                continue

            existing = db.query(Proyecto).filter_by(topic_slug=p["topic_slug"]).first()
            if existing:
                existing.nombre_comercial          = p["nombre_comercial"]
                existing.cliente_id                = cliente_id
                existing.tipo_tecnologia           = "solar"
                existing.potencia_instalada_kwp    = p["potencia_instalada_kwp"]
                existing.cantidad_total_paneles    = p["cantidad_total_paneles"]
                existing.produccion_especifica_kwh_kwp = p["produccion_especifica_kwh_kwp"]
                proyectos_by_slug[p["topic_slug"]] = existing.id
                ok_upd += 1
                print(f"  UPD {p['nombre_comercial']}")
            else:
                nuevo = Proyecto(
                    nombre_comercial               = p["nombre_comercial"],
                    topic_slug                     = p["topic_slug"],
                    cliente_id                     = cliente_id,
                    tipo_tecnologia                = "solar",
                    potencia_instalada_kwp         = p["potencia_instalada_kwp"],
                    cantidad_total_paneles         = p["cantidad_total_paneles"],
                    produccion_especifica_kwh_kwp  = p["produccion_especifica_kwh_kwp"],
                    estado                         = "en_operacion",
                )
                db.add(nuevo)
                db.flush()
                proyectos_by_slug[p["topic_slug"]] = nuevo.id
                ok_new += 1
                print(f"  NEW {p['nombre_comercial']}")

        db.commit()
        print(f"Proyectos: {ok_new} nuevos, {ok_upd} actualizados, {err} errores")

        # ── 3. Inversionistas ─────────────────────────────────────────────────
        print("\n--- INVERSIONISTAS ---")
        ok = skip = err = 0

        # Par (proyecto_id, cliente_id) ya existentes en BD
        existing_pairs: set[tuple[int, int]] = set(
            db.query(ProyectoInversionista.proyecto_id, ProyectoInversionista.cliente_id).all()
        )

        for inv in INVERSIONISTAS:
            proy_id = proyectos_by_slug.get(inv["slug"])
            cli_id  = clientes_by_nit.get(inv["nit"])

            if not proy_id:
                print(f"  ERR slug '{inv['slug']}' no encontrado")
                err += 1
                continue
            if not cli_id:
                print(f"  ERR NIT '{inv['nit']}' no encontrado")
                err += 1
                continue
            if (proy_id, cli_id) in existing_pairs:
                skip += 1
                continue

            db.add(ProyectoInversionista(
                proyecto_id              = proy_id,
                cliente_id               = cli_id,
                porcentaje_participacion = inv["pct"],
            ))
            existing_pairs.add((proy_id, cli_id))
            ok += 1
            print(f"  NEW inv {inv['slug']} / {inv['nit']} ({inv['pct']*100:.2f}%)")

        db.commit()
        print(f"Inversionistas: {ok} nuevos, {skip} ya existían, {err} errores")

        print("\n✓ Carga completa sin errores.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR — rollback: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
