"""
Inserta las 17 fallas de mayo 2026 en la base de datos.
Uso:
    cd unergy-operaciones-backend
    python scripts/insertar_fallas_mayo2026.py [--dry-run]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date, time
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.fallas import (
    Falla, FallaSeguimiento, FallaCatEstado, FallaCatPrioridad,
    FallaCatTipo, FallaCatResolucion,
)
from app.models.proyectos import Proyecto

DRY_RUN = "--dry-run" in sys.argv


def p(d, fmt="%d/%m/%Y"):
    return datetime.strptime(d.strip(), fmt).date() if d.strip() else None


def dt(s, fmt="%d/%m/%Y %H:%M"):
    return datetime.strptime(s.strip(), fmt) if s.strip() else None


def t(s):
    if not s.strip():
        return None
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def find_proj(db: Session, keyword: str):
    keyword = keyword.strip()
    # exact
    r = db.query(Proyecto).filter(Proyecto.nombre_comercial == keyword).first()
    if r:
        return r
    # ilike
    r = db.query(Proyecto).filter(Proyecto.nombre_comercial.ilike(f"%{keyword}%")).first()
    if r:
        return r
    return None


def main():
    db = SessionLocal()
    try:
        # ── catálogos ────────────────────────────────────────────────────────
        def estado(codigo):
            return db.query(FallaCatEstado).filter(FallaCatEstado.codigo == codigo).first()

        def prio(codigo):
            return db.query(FallaCatPrioridad).filter(FallaCatPrioridad.codigo == codigo).first()

        def tipo(id_):
            return db.query(FallaCatTipo).filter(FallaCatTipo.id == id_).first()

        def resolucion(id_):
            return db.query(FallaCatResolucion).filter(FallaCatResolucion.id == id_).first()

        # IDs de estado
        ST = {
            "terminada": estado("cerrada"),
            "en_revision": estado("en_gestion"),
            "en_proceso": estado("en_gestion"),
        }
        # IDs de prioridad: Alta → grave (2), Media → media (3)
        PR = {"Alta": prio("grave"), "Media": prio("media")}

        # tipos más usados  (id según catálogo consultado)
        TIPOS = {
            "2.0": tipo(27),   # Desconexión sin causa
            "2.1": tipo(28),   # Fusible de string / caída tensión
            "2.2_inv": tipo(35),  # Falla de inversor
            "2.2_hsp": tipo(40),  # Punto caliente (hotspot)
            "2.4": tipo(31),   # Relé de protección
            "2.11": tipo(37),  # Tracker no opera
            "com_perdida": tipo(5),    # Comunicación perdida
            "1.11": tipo(26),  # Falla plataforma monitoreo
        }
        # resoluciones (id)
        RES = {
            "visita": resolucion(2),     # Visita técnica
            "remota": resolucion(6),     # Resolución remota
            "or": resolucion(5),         # Intervención operador de red
            "cambio": resolucion(3),     # Cambio de componente
            "otro": resolucion(8),       # Otro
        }

        # usuario registrador (operaciones@unergy.io = id 2)
        from app.models.usuarios import Usuario
        registrador = db.query(Usuario).filter(Usuario.email == "operaciones@unergy.io").first()
        if not registrador:
            registrador = db.query(Usuario).order_by(Usuario.id).first()
        reg_id = registrador.id

        # ── código interno ───────────────────────────────────────────────────
        from sqlalchemy import func
        count = db.query(func.count(Falla.id)).scalar() or 0
        year = 2026

        def gen_codigo():
            nonlocal count
            count += 1
            return f"FAL-{year}-{count:05d}"

        # ── datos de fallas ──────────────────────────────────────────────────
        rows = [
            # (legado, proyecto_kw, tipo_key, estado_key, prioridad, fecha_id, hora_id,
            #  fecha_oc, fecha_res, descripcion, seguimiento, centinela, resolucion_key)
            ("F-00001", "Copey",           "2.1",      "terminada",  "Media",
             "02/05/2026", "12:58", "01/05/2026 00:00", "02/05/2026 13:00",
             "Desconexión por caída de tensión en fase 2",
             "Reconectado manualmente por vigilante",
             "Juan José Unergy", "otro"),

            ("F-00002", "El Paso",          "2.11",     "en_revision","Media",
             "02/05/2026", "09:10", "02/05/2026 09:10", "",
             "Generación inferior a la esperada; posible mala orientación de trackers",
             "Validación en campo (condición climática nublada reportada)",
             "Juan José Unergy", "visita"),

            ("F-00003", "Nestlé",           "2.2_hsp",  "en_revision","Alta",
             "02/05/2026", "12:53", "02/05/2026 12:53", "",
             "Detección de punto caliente en inversor 3 (riesgo de daño)",
             "Programación de intervención técnica",
             "Miguel Bello", "visita"),

            ("F-00004", "Cacica",           "2.0",      "terminada",  "Media",
             "02/05/2026", "20:54", "02/05/2026 20:54", "03/05/2026 07:49",
             "Desconexión de plantas en horas de la tarde",
             "Restablecidas automáticamente al día siguiente",
             "Operación", "remota"),

            ("F-00005", "Cacica",           "2.4",      "en_revision","Alta",
             "02/05/2026", "20:54", "02/05/2026 20:54", "",
             "No operación del control remoto del reconectador",
             "Requiere revisión de sistema de control",
             "Operación", "visita"),

            ("F-00006", "San Diego Sur",    "2.0",      "terminada",  "Alta",
             "03/05/2026", "08:41", "03/05/2026 08:41", "03/05/2026 13:58",
             "Planta fuera de operación por disparo",
             "Restablecida operación",
             "Daniel Gómez", "visita"),

            ("F-00007", "San Diego Sur",    "com_perdida","terminada","Media",
             "03/05/2026", "13:58", "03/05/2026 13:58", "03/05/2026 14:00",
             "Pérdida de comunicación en inversores",
             "Comunicación restablecida",
             "Operación", "remota"),

            ("F-00008", "Copey",            "2.0",      "en_revision","Alta",
             "03/05/2026", "14:01", "03/05/2026 14:01", "",
             "Desconexión simultánea de múltiples proyectos",
             "Requiere intervención en campo",
             "Operación", "visita"),

            ("F-00009", "Copey",            "2.1",      "en_revision","Alta",
             "04/05/2026", "08:00", "04/05/2026 08:00", "",
             "Proyecto sin energía",
             "Verificación con operador (posible red externa)",
             "Operación", "or"),

            ("F-00010", "Cedillanos",       "2.0",      "en_revision","Media",
             "04/05/2026", "08:10", "04/05/2026 08:10", "",
             "Proyecto apagado",
             "Solicitud de revisión técnica",
             "Operación", "visita"),

            ("F-00011", "Uruaco",           "2.2_inv",  "en_revision","Media",
             "04/05/2026", "08:15", "04/05/2026 08:15", "",
             "Operación parcial del sistema",
             "Validación de inversor",
             "Operación", "visita"),

            ("F-00012", "Gandalf",          "2.2_inv",  "en_revision","Alta",
             "04/05/2026", "09:00", "04/05/2026 09:00", "",
             "Equipo fuera de servicio",
             "En espera de reposición por garantía",
             "Miguel Bello", "cambio"),

            ("F-00013", "Gandalf",          "2.2_inv",  "en_revision","Alta",
             "04/05/2026", "09:05", "04/05/2026 09:05", "",
             "Cableado AC estallado cercano al inversor",
             "Programado cambio de cableado",
             "Miguel Bello", "cambio"),

            ("F-00014", "Gandalf",          "com_perdida","en_revision","Alta",
             "04/05/2026", "09:10", "04/05/2026 09:10", "",
             "Sistema de comunicación no operativo",
             "Revisión de equipo Starlink",
             "Operación", "visita"),

            ("F-00015", "Nestlé",           "1.11",     "terminada",  "Alta",
             "05/05/2026", "08:00", "05/05/2026 08:00", "05/05/2026 10:00",
             "No conexión por falla en plataforma de monitoreo",
             "Servicio restablecido",
             "Operación", "remota"),

            ("F-00016", "La Mesa",          "1.11",     "en_revision","Alta",
             "05/05/2026", "08:00", "05/05/2026 08:00", "",
             "Sin datos y sin opción de reconexión",
             "Pendiente validación",
             "Operación", "visita"),

            ("F-00017", "Cañahuate",        "2.2_inv",  "terminada",  "Media",
             "05/05/2026", "08:10", "05/05/2026 08:10", "05/05/2026 11:00",
             "Operación parcial por falla en inversor",
             "Equipo restablecido",
             "Operación", "remota"),
        ]

        print(f"\n{'[DRY-RUN] ' if DRY_RUN else ''}Insertando {len(rows)} fallas...\n")
        print(f"{'Legado':<10} {'Proyecto':<30} {'Código':<18} {'Estado'}")
        print("-" * 75)

        created = []
        skipped = []

        for row in rows:
            (legado, proj_kw, tipo_key, estado_key, prio_key,
             fi, hi, fo, fr, desc, seg_nota, centinela_v, res_key) = row

            proj = find_proj(db, proj_kw)
            if not proj:
                print(f"{legado:<10} SALTADO (proyecto no encontrado: '{proj_kw}')")
                skipped.append(legado)
                continue

            falla = Falla(
                codigo_interno=gen_codigo(),
                registrado_por_id=reg_id,
                proyecto_id=proj.id,
                tipo_id=TIPOS[tipo_key].id,
                estado_id=ST[estado_key].id,
                prioridad_id=PR[prio_key].id,
                resolucion_id=RES[res_key].id if res_key and RES.get(res_key) else None,
                descripcion=desc,
                fecha_identificacion=p(fi),
                hora_identificacion=t(hi),
                fecha_ocurrencia=dt(fo) if fo.strip() else None,
                fecha_resolucion=dt(fr) if fr.strip() else None,
                centinela=centinela_v,
            )
            print(f"{legado:<10} {proj.nombre_comercial:<30} {falla.codigo_interno:<18} {estado_key}")

            if not DRY_RUN:
                db.add(falla)
                db.flush()  # obtener falla.id
                if seg_nota:
                    seg = FallaSeguimiento(
                        falla_id=falla.id,
                        usuario_id=reg_id,
                        nota=seg_nota,
                        estado_nuevo_id=ST[estado_key].id,
                    )
                    db.add(seg)
                created.append(legado)

        if not DRY_RUN:
            db.commit()
            print(f"\n✓ {len(created)} fallas insertadas.")
        else:
            print(f"\n[DRY-RUN] Se insertarían {len(rows) - len(skipped)} fallas.")

        if skipped:
            print(f"  Saltadas: {skipped}")

    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
