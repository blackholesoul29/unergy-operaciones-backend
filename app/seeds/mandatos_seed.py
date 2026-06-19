"""Seed de la pestaña Mandatos.

Ejecutar una sola vez después de aplicar la migración 021:
    python -m app.seeds.mandatos_seed
"""
from datetime import date
from sqlalchemy import select
from app.core.database import SessionLocal
from app.models.mandatos import Mandato, MandatoInversionista

MAESTRA = [
    {"nombre": "Sun-Capital", "correos": ["sgutierrez@kaienergy.co", "Facturacion@kaienergy.co", "epatino@ayura.co", "dcuervo@kaienergy.co"],
     "proyectos": ["Minigranja Solar Baraya", "Minigranja Solar Mapalé", "Minigranja Solar Ibirico"]},
    {"nombre": "Solenium", "correos": ["juliana@solenium.co", "juanjose@solenium.co"],
     "proyectos": ["Minigranja Solar Baraya", "Minigranja Solar El Son", "Minigranja Solar Cacica", "Minigranja Solar Piloneras"]},
    {"nombre": "Jemma", "correos": ["Contador@tesla.com.co", "operaciones@tesla.com.co", "ventas@tesla.com.co", "gerente.administrativo@tesla.com.co"],
     "proyectos": ["Minigranja Solar El Son"]},
    {"nombre": "Evolti", "correos": ["naos@evolti.co", "gerencia@evolti.co", "contabilidad.minigranjas@evolti.co", "marcela.cajigas@evolti.co"],
     "proyectos": ["GD NAOS 1", "GD NAOS 2", "GD NAOS 3", "GD Polaris 1", "GD Polaris 2", "GD Delta 1"]},
    {"nombre": "Estrada", "correos": ["gerencia@invesarcia.com", "strada.asociados.sas@outlook.com"],
     "proyectos": ["Minigranja Solar La Reserva"]},
    {"nombre": "Beatriz", "correos": ["v.vargas129@gmail.com"], "proyectos": ["Minigranja Solar Uruaco"]},
    {"nombre": "Credicorp", "correos": ["wpire@credicorpcapital.com", "gerenciadegestion@credicorpcapital.com", "vcantor@credicorpcapital.com", "impuestos@credicorpcapital.com"],
     "proyectos": ["El Llano SAS BIC"]},
    {"nombre": "Bayunca", "correos": ["borgogna@thesanusa.us", "barney@thesanusa.us"], "proyectos": ["Bayunca"]},
    {"nombre": "San Onofre", "correos": ["apuente@novavalorenergy.com", "rpertuz@novavalorenergy.com"], "proyectos": ["GD 1MVA San Onofre"]},
    {"nombre": "Ayurá", "correos": ["arodriguez@ayura.co", "jclavijo@ayura.co", "epatino@ayura.co"],
     "proyectos": ["Salud Vegas SAS", "Minigranja Solar Cacica", "Minigranja Solar Piloneras"]},
    {"nombre": "Marimonda", "correos": ["Lahormigasolarsas@gmail.com"], "proyectos": ["Marimonda"]},
    {"nombre": "Agustín", "correos": ["fonsarsas@hotmail.com", "fonsarsas@gmail.com"], "proyectos": ["GD Agustín 1", "GD Agustín 2"]},
    {"nombre": "Suno", "correos": ["cesar@suno.finance", "admin@suno.finance", "nicolas@suno.finance", "gabriel@suno.finance"],
     "proyectos": ["Almacen Amc Sas", "Arcillas San Simon", "Central De Maderas G&S"]},
    {"nombre": "Yurbaqua", "correos": ["angela.neuta@enexaenergy.com", "daniel.maya@enexaenergy.com"], "proyectos": ["PSF - Yurbaqua"]},
    {"nombre": "Yuan Solar", "correos": ["jdavid.rincon@femenergia.com", "arincon@madigas.com.co"], "proyectos": ["GD Yuan Solar"]},
    {"nombre": "Sirius", "correos": ["Sercha_18@hotmail.com", "facturasingenieriaquantum@hotmail.com"], "proyectos": ["Sirius"]},
    {"nombre": "Catedral", "correos": ["contacto@pelletco.com.co"], "proyectos": ["Catedral"]},
    {"nombre": "Sol&Cielo", "correos": ["M.barrios@sol-cielo.com", "Info@sol-cielo.com", "Gerencia@sol-cielo.com", "a.gutierrez@sol-cielo.com"],
     "proyectos": ["Sol y Cielo 7 Los Bongos", "Sol y Cielo 9 Ciénaga"]},
    {"nombre": "Astrolumen", "correos": ["energyinvestmentgroup2019@gmail.com"], "proyectos": ["Astrolumen"]},
    {"nombre": "Biosolar", "correos": ["inversionesbiososteniblessas@gmail.com"], "proyectos": ["Biosolar"]},
    {"nombre": "San Pelayo", "correos": ["nicolas.o@cgm-i.com", "karen.palacio@cgm-i.com"], "proyectos": ["San Pelayo"]},
]

P_MAYO = date(2025, 5, 1)
OBS = "novedad en la contabilización del arriendo"
CMU_CORRECCION = ["CMU0988", "CMU0993", "CMU0996", "CMU1003", "CMU1005", "CMU1016", "CMU1017", "CMU1018", "CMU1019"]


def _inv_id(db, nombre):
    return db.execute(select(MandatoInversionista.id).where(MandatoInversionista.nombre == nombre)).scalar_one_or_none()


def seed_maestra(db):
    """Inserta la tabla maestra (idempotente por nombre). No commitea."""
    for item in MAESTRA:
        existe = db.execute(
            select(MandatoInversionista).where(MandatoInversionista.nombre == item["nombre"])
        ).scalar_one_or_none()
        if not existe:
            db.add(MandatoInversionista(**item))


def ensure_maestra():
    """Asegura que la maestra exista. Seguro de llamar en cada arranque."""
    db = SessionLocal()
    try:
        seed_maestra(db)
        db.commit()
    finally:
        db.close()


def run():
    db = SessionLocal()
    try:
        # ── Maestra ──
        seed_maestra(db)
        db.commit()

        suno_id = _inv_id(db, "Suno")

        # ── Datos de prueba mayo 2025 (idempotente por cmu+periodo) ──
        def upsert(cmu, **kw):
            existe = db.execute(select(Mandato).where(Mandato.cmu == cmu, Mandato.periodo == P_MAYO)).scalar_one_or_none()
            if existe:
                return
            db.add(Mandato(cmu=cmu, periodo=P_MAYO, **kw))

        for cmu in CMU_CORRECCION:
            upsert(cmu, estado="con_correcciones", observacion=OBS,
                   fecha_envio_revisoria=date(2025, 5, 10))

        upsert("CMU0982", estado="enviado_revisoria", tercero="Suno", inversionista_id=suno_id,
               fecha_envio_revisoria=date(2025, 5, 10))
        upsert("CMU0975", estado="enviado_inversionista", tercero="Fondo Capital Privado",
               inversionista_id=suno_id, fecha_envio_revisoria=date(2025, 5, 10),
               fecha_firmado=date(2025, 5, 14), fecha_envio_inversionista=date(2025, 5, 15),
               pdf_firmado_nombre="CMU0975_firmado.pdf", pdf_firmado_ruta="uploads/mandatos/CMU0975_firmado.pdf")
        upsert("CMU0979", estado="enviado_inversionista", tercero="Suno", inversionista_id=suno_id,
               fecha_envio_revisoria=date(2025, 5, 10), fecha_firmado=date(2025, 5, 14),
               fecha_envio_inversionista=date(2025, 5, 15),
               pdf_firmado_nombre="CMU0979_firmado.pdf", pdf_firmado_ruta="uploads/mandatos/CMU0979_firmado.pdf")
        db.commit()
        print("Seed mandatos OK")
    finally:
        db.close()


if __name__ == "__main__":
    run()
