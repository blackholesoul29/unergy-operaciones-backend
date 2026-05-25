"""
Ejecutar una sola vez después de crear las tablas:
    python -m app.seeds.seed_data
"""
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import (
    Usuario, FallaCatCategoria, FallaCatTipo, FallaCatEstado,
    FallaCatPrioridad, FallaCatResolucion, PromoterCatalogoRequisito,
)


USUARIOS = [
    {"email": "juanjose@unergy.io",    "nombre": "Juan José Pacheco Arias", "rol": "admin"},
    {"email": "laurah@unergy.io",      "nombre": "Laura Vanessa Hurtado",   "rol": "admin"},
    {"email": "jessica@unergy.io",     "nombre": "Jessica",                 "rol": "admin"},
    {"email": "nicolas@unergy.io",     "nombre": "Nicolás Villegas",        "rol": "operaciones"},
    {"email": "eduardo@unergy.io",     "nombre": "Eduardo",                 "rol": "admin"},
    {"email": "victor@unergy.io",      "nombre": "Víctor",                  "rol": "admin"},
    {"email": "camilo@unergy.io",      "nombre": "Camilo",                  "rol": "operaciones"},
    {"email": "danielg@unergy.io",     "nombre": "Daniel G.",               "rol": "operaciones"},
    {"email": "hillary@unergy.io",     "nombre": "Hillary",                 "rol": "admin"},
    {"email": "operaciones@unergy.io", "nombre": "Operaciones Unergy",      "rol": "operaciones"},
]

CATEGORIAS_FALLA = [
    {"codigo": "inversor",      "etiqueta": "Inversor",             "color_hex": "#EF4444", "orden": 1},
    {"codigo": "comunicacion",  "etiqueta": "Comunicación",         "color_hex": "#F97316", "orden": 2},
    {"codigo": "produccion",    "etiqueta": "Producción baja",      "color_hex": "#EAB308", "orden": 3},
    {"codigo": "red",           "etiqueta": "Red eléctrica",        "color_hex": "#8B5CF6", "orden": 4},
    {"codigo": "estructura",    "etiqueta": "Estructura / Civil",   "color_hex": "#6B7280", "orden": 5},
    {"codigo": "medicion",      "etiqueta": "Medición / Frontera",  "color_hex": "#3B82F6", "orden": 6},
    {"codigo": "otro",          "etiqueta": "Otro",                 "color_hex": "#9CA3AF", "orden": 7},
]

TIPOS_FALLA = [
    # Inversor
    {"categoria": "inversor", "codigo": "inv_falla_total",   "etiqueta": "Falla total de inversor"},
    {"categoria": "inversor", "codigo": "inv_falla_parcial", "etiqueta": "Falla parcial de inversor"},
    {"categoria": "inversor", "codigo": "inv_sobrecalent",   "etiqueta": "Sobrecalentamiento"},
    {"categoria": "inversor", "codigo": "inv_desconexion",   "etiqueta": "Desconexión intempestiva"},
    # Comunicación
    {"categoria": "comunicacion", "codigo": "com_perdida",     "etiqueta": "Comunicación perdida"},
    {"categoria": "comunicacion", "codigo": "com_intermitente","etiqueta": "Comunicación intermitente"},
    # Producción
    {"categoria": "produccion", "codigo": "prod_baja_pr",    "etiqueta": "Performance Ratio bajo"},
    {"categoria": "produccion", "codigo": "prod_cero",       "etiqueta": "Producción en cero"},
    # Red
    {"categoria": "red", "codigo": "red_desbalance",    "etiqueta": "Desbalance de tensión"},
    {"categoria": "red", "codigo": "red_corte",         "etiqueta": "Corte de suministro"},
    {"categoria": "red", "codigo": "red_calidad",       "etiqueta": "Calidad de energía"},
    # Estructura
    {"categoria": "estructura", "codigo": "estr_tracker",  "etiqueta": "Tracker en mesa / falla"},
    {"categoria": "estructura", "codigo": "estr_panel",    "etiqueta": "Panel dañado"},
    # Medición
    {"categoria": "medicion", "codigo": "med_lectura",  "etiqueta": "Error de lectura"},
    {"categoria": "medicion", "codigo": "med_sello",    "etiqueta": "Sello comprometido"},
    # Otro
    {"categoria": "otro", "codigo": "otro_general", "etiqueta": "Otro / Sin categoría"},
]

ESTADOS_FALLA = [
    {"codigo": "abierta",      "etiqueta": "Abierta",       "color_hex": "#EF4444", "orden": 1, "es_estado_final": False},
    {"codigo": "en_gestion",   "etiqueta": "En gestión",    "color_hex": "#F97316", "orden": 2, "es_estado_final": False},
    {"codigo": "en_espera",    "etiqueta": "En espera",     "color_hex": "#EAB308", "orden": 3, "es_estado_final": False},
    {"codigo": "cerrada",      "etiqueta": "Cerrada",       "color_hex": "#22C55E", "orden": 4, "es_estado_final": True},
    {"codigo": "sin_solucion", "etiqueta": "Sin solución",  "color_hex": "#6B7280", "orden": 5, "es_estado_final": True},
]

PRIORIDADES = [
    {"codigo": "critica", "etiqueta": "Crítica", "color_hex": "#DC2626", "nivel": 1},
    {"codigo": "grave",   "etiqueta": "Grave",   "color_hex": "#EA580C", "nivel": 2},
    {"codigo": "media",   "etiqueta": "Media",   "color_hex": "#CA8A04", "nivel": 3},
    {"codigo": "leve",    "etiqueta": "Leve",    "color_hex": "#16A34A", "nivel": 4},
]

RESOLUCIONES = [
    {"codigo": "reinicio_inversor",  "etiqueta": "Reinicio de inversor"},
    {"codigo": "visita_tecnica",     "etiqueta": "Visita técnica"},
    {"codigo": "cambio_componente",  "etiqueta": "Cambio de componente"},
    {"codigo": "actualizacion_fw",   "etiqueta": "Actualización firmware"},
    {"codigo": "intervencion_red",   "etiqueta": "Intervención operador de red"},
    {"codigo": "resolucion_remota",  "etiqueta": "Resolución remota"},
    {"codigo": "sin_accion",         "etiqueta": "Sin acción requerida"},
    {"codigo": "otro",               "etiqueta": "Otro"},
]

REQUISITOS_PROMOTOR = [
    {"id": "9.1",  "nombre": "Registro del proyecto ante el CND",                                                                       "plazo_dias": 90},
    {"id": "9.2",  "nombre": "Agente generador AGGE y GD",                                                                              "plazo_dias": 30},
    {"id": "9.3",  "nombre": "Información básica AGGE y GD",                                                                            "plazo_dias": 30},
    {"id": "9.4",  "nombre": "Ajuste y coordinación de protecciones (comunicación firmada por el transportador)",                        "plazo_dias": 7},
    {"id": "9.5",  "nombre": "Coordinar actividades para la incorporación al SIN e indisponibilidades excluidas (AGGE con CEN < 5MW y DER)", "plazo_dias": 90},
    {"id": "9.6",  "nombre": "Fronteras comerciales AGGE y GD",                                                                         "plazo_dias": 3},
    {"id": "9.7",  "nombre": "Certificado de la conexión y capacidad de transporte asignada AGGE y GD",                                 "plazo_dias": 3},
    {"id": "9.8",  "nombre": "Declaración del programa de generación",                                                                  "plazo_dias": 2},
    {"id": "9.9",  "nombre": "Certificados de cumplimiento de la reglamentación vigente",                                               "plazo_dias": 2},
    {"id": "9.10", "nombre": "Declaración de fecha de entrada en operación y su capacidad máxima declarada",                            "plazo_dias": 1},
    {"id": "FDOC", "nombre": "Solicitud de actualización de la FDOC o FIPPS",                                                           "plazo_dias": None},
]


def seed():
    db = SessionLocal()
    try:
        # Usuarios — inserta si no existe, actualiza rol si cambió
        for u in USUARIOS:
            existing = db.query(Usuario).filter_by(email=u["email"]).first()
            if existing:
                existing.rol = u["rol"]
                existing.nombre = u["nombre"]
            else:
                db.add(Usuario(
                    email=u["email"],
                    nombre=u["nombre"],
                    rol=u["rol"],
                    password_hash=hash_password("Unergy2025!"),
                    activo=True,
                ))

        # Categorías de falla
        cat_map = {}
        for c in CATEGORIAS_FALLA:
            obj = db.query(FallaCatCategoria).filter_by(codigo=c["codigo"]).first()
            if not obj:
                obj = FallaCatCategoria(**c)
                db.add(obj)
                db.flush()
            cat_map[c["codigo"]] = obj.id

        # Tipos de falla
        for t in TIPOS_FALLA:
            if not db.query(FallaCatTipo).filter_by(codigo=t["codigo"]).first():
                db.add(FallaCatTipo(
                    categoria_id=cat_map[t["categoria"]],
                    codigo=t["codigo"],
                    etiqueta=t["etiqueta"],
                ))

        # Estados de falla
        for e in ESTADOS_FALLA:
            if not db.query(FallaCatEstado).filter_by(codigo=e["codigo"]).first():
                db.add(FallaCatEstado(**e))

        # Prioridades
        for p in PRIORIDADES:
            if not db.query(FallaCatPrioridad).filter_by(codigo=p["codigo"]).first():
                db.add(FallaCatPrioridad(**p))

        # Resoluciones
        for r in RESOLUCIONES:
            if not db.query(FallaCatResolucion).filter_by(codigo=r["codigo"]).first():
                db.add(FallaCatResolucion(**r))

        # Catálogo promotor
        for req in REQUISITOS_PROMOTOR:
            if not db.query(PromoterCatalogoRequisito).filter_by(id=req["id"]).first():
                db.add(PromoterCatalogoRequisito(**req))

        db.commit()
        print("OK Datos semilla insertados correctamente")
    except Exception as e:
        db.rollback()
        print(f"ERROR en seed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
