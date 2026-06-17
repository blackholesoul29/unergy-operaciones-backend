"""
Ejecutar una sola vez después de crear las tablas:

    # Producción — escribe las contraseñas cifradas a seed_passwords.json.enc
    SEED_FERNET_KEY=... python -m app.seeds.seed_data

    # Desarrollo — imprime las contraseñas a stdout (NUNCA en producción)
    python -m app.seeds.seed_data --dev

Seguridad: NO se hardcodean contraseñas. Cada usuario nuevo recibe una
contraseña aleatoria fuerte y queda con `force_password_reset=True`, por lo que
debe cambiarla en el primer acceso. Las contraseñas iniciales se entregan una
sola vez: por stdout (--dev) o cifradas con Fernet (producción).
"""
import argparse
import datetime as _dt
import json
import os

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.utils.password_generator import generate_secure_password
from app.models import (
    Usuario, FallaCatCategoria, FallaCatTipo, FallaCatEstado,
    FallaCatPrioridad, FallaCatResolucion, PromoterCatalogoRequisito,
)

# Archivo donde se escriben las contraseñas cifradas en producción.
# NUNCA se versiona (ver .gitignore) — es un artefacto de despliegue efímero.
SEED_PASSWORDS_FILE = os.path.join(os.path.dirname(__file__), "seed_passwords.json.enc")


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
    {"codigo": "programado",   "etiqueta": "Programado",    "color_hex": "#3B82F6", "orden": 0, "es_estado_final": False},
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


def _emit_credentials(creds: list[dict], dev: bool) -> None:
    """Entrega las contraseñas iniciales generadas, de forma segura.

    dev=True  → imprime a stdout (solo para desarrollo local).
    dev=False → cifra con Fernet (clave en `SEED_FERNET_KEY`) y escribe a disco.
                Si no hay clave, aborta en vez de filtrar las contraseñas.
    """
    if not creds:
        print("OK No se crearon usuarios nuevos — sin contraseñas que entregar")
        return

    if dev:
        print("\n⚠️  CONTRASEÑAS INICIALES (solo desarrollo — cámbialas en el primer acceso):")
        for c in creds:
            print(f"   {c['email']:<28} {c['password']}")
        print()
        return

    key = os.environ.get("SEED_FERNET_KEY")
    if not key:
        raise SystemExit(
            "ERROR: define SEED_FERNET_KEY (clave Fernet) para cifrar las "
            "contraseñas iniciales, o usa --dev para imprimirlas en local. "
            "Genera una con: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )

    from cryptography.fernet import Fernet

    payload = json.dumps(
        {
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "note": "Contraseñas iniciales — el usuario DEBE cambiarlas en el primer acceso.",
            "credentials": creds,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    token = Fernet(key.encode()).encrypt(payload)
    # 0600: solo el propietario puede leerlo.
    fd = os.open(SEED_PASSWORDS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(token)
    print(
        f"OK {len(creds)} contraseñas cifradas escritas en {SEED_PASSWORDS_FILE}\n"
        f"   Descífralas con SEED_FERNET_KEY y entrégalas por un canal seguro."
    )


def seed(dev: bool = False):
    db = SessionLocal()
    nuevas_credenciales: list[dict] = []
    try:
        # Usuarios — inserta si no existe, actualiza rol si cambió.
        # Los usuarios nuevos reciben una contraseña aleatoria fuerte y quedan
        # con force_password_reset=True (deben cambiarla en el primer acceso).
        for u in USUARIOS:
            existing = db.query(Usuario).filter_by(email=u["email"]).first()
            if existing:
                existing.rol = u["rol"]
                existing.nombre = u["nombre"]
            else:
                initial_password = generate_secure_password()
                db.add(Usuario(
                    email=u["email"],
                    nombre=u["nombre"],
                    rol=u["rol"],
                    password_hash=hash_password(initial_password),
                    activo=True,
                    force_password_reset=True,
                ))
                nuevas_credenciales.append({"email": u["email"], "password": initial_password})

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

    # Entrega de contraseñas iniciales fuera de la transacción de BD.
    _emit_credentials(nuevas_credenciales, dev=dev)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga de datos semilla")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Imprime las contraseñas iniciales en stdout (solo desarrollo local)",
    )
    args = parser.parse_args()
    seed(dev=args.dev)
