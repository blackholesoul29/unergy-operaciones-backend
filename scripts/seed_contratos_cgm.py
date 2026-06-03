"""
Seed: carga contratos CGM/Representación a contratos_servicio.
Ejecutar una sola vez tras el deploy de migration 024.

    python scripts/seed_contratos_cgm.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.contratos import ContratoServicio

CONTRATOS = [
    # ── La Reserva ──────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0012 - La Reserva", codigo_sun_factory="COLSANT9P1",
        portafolio="Suno - Solenium - Sandra Estrada", inversionista_nombre="Strada Asociados S.A.S.",
        estado="vigente", tarifa_admin=0.038, fecha_firma_contrato="2024-04-02",
        enlace_drive="https://drive.google.com/file/d/1MJ-zyaEgVIKiqy4XbLjakmYoI3h2Mr0u/view?usp=drive_link",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0,        "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0,        "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    dict(
        proyecto_nombre="Minigranja 0012 - La Reserva", codigo_sun_factory="COLSANT9P1",
        portafolio="Suno - Solenium - Sandra Estrada",
        inversionista_nombre="Inversiones Estrada Arbelaez y CIA S. en C.",
        estado="vigente", tarifa_admin=0.038, fecha_firma_contrato="2024-04-02",
        enlace_drive="https://drive.google.com/file/d/18Cx6N_dB1GghULWok9SzGu79XFw47V/view?usp=drive_link",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0,        "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0,        "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── GD NAOS 1 ───────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD NAOS 1", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
        estado="vigente", fecha_firma_contrato="2024-07-17",
        enlace_drive="https://drive.google.com/file/d/1u0-xNyfdvhwZk3AokNyFsGjzn8PNfgtO/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 7.0,          "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 7.364},
            {"año": 2026, "ipc": 5.1,  "valor": 7.739564},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 3.0,          "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 3.156},
            {"año": 2026, "ipc": 5.1,  "valor": 3.316956},
        ],
    ),
    # ── El Son ──────────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0015 - El Son", codigo_sun_factory="COLCEST45P1",
        portafolio="Suno - Solenium", inversionista_nombre="Nacional de Transformadores S.A.S.",
        estado="vigente", tarifa_admin=0.038, fecha_firma_contrato="2024-08-09",
        enlace_drive="https://drive.google.com/file/d/1mNHMt12XnT8rvGnxhE3a7Ub9MEQsQWn1/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    dict(
        proyecto_nombre="Minigranja 0015 - El Son", codigo_sun_factory="COLCEST45P1",
        portafolio="Suno - Solenium", inversionista_nombre="Unergy S.A.S",
        estado="vigente", tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── Baraya ──────────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
        portafolio="Suno - Solenium", inversionista_nombre="Solenium S.A.S",
        estado="vigente", tarifa_admin=0.038, fecha_firma_contrato="2024-01-19",
        enlace_drive="https://drive.google.com/file/d/1kWhy9drgx7z81URpYJ3ZjfWnj5h6GeYA/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    dict(
        proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
        portafolio="Suno - Solenium", inversionista_nombre="SOMOS BOGOTÁ USME SAS",
        estado="vigente", tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    dict(
        proyecto_nombre="Minigranja 0002 - Baraya", codigo_sun_factory="COLSUCT17P2",
        portafolio="Suno - Solenium", inversionista_nombre="Unergy S.A.S",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── La Cacica ───────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0040 - La Cacica", codigo_sun_factory="COLCEST55P1",
        portafolio="Serranía de Perijá", inversionista_nombre="Ayurá S.A.S.",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── Las Piloneras ───────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0041 - Las piloneras", codigo_sun_factory="COLCEST55P2",
        portafolio="Serranía de Perijá", inversionista_nombre="Ayurá S.A.S.",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── Chimá Oriente ───────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0030 - Chimá Oriente", codigo_sun_factory="COLCORT7P1",
        portafolio="Cox", inversionista_nombre="Solenium S.A.S",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
        indexacion_cgm=[], indexacion_representacion=[],
    ),
    dict(
        proyecto_nombre="Minigranja 0030 - Chimá Oriente", codigo_sun_factory="COLCORT7P1",
        portafolio="Cox", inversionista_nombre="Ayurá S.A.S.",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
        indexacion_cgm=[], indexacion_representacion=[],
    ),
    # ── Ibirico ─────────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0021 - Ibirico", codigo_sun_factory="COLCEST49P2",
        portafolio="Kai",
        inversionista_nombre="FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── El Mapalé ───────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0020 - El Mapalé", codigo_sun_factory="COLCEST45P6",
        portafolio="Kai",
        inversionista_nombre="FIDEICOMISOS BBVA ASSET MANAGEMENT S. A. SOCIEDAD FIDUCIARIA",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=0.0, tarifa_representacion=0.0,
        indexacion_cgm=[], indexacion_representacion=[],
    ),
    # ── Chiriguaná Norte 2 ──────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0075 - Chiriguaná Norte 2", codigo_sun_factory="COLCEST60P4",
        portafolio="Skandia",
        inversionista_nombre="PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── Chiriguaná Norte 4 ──────────────────────────────────────────────────
    dict(
        proyecto_nombre="Minigranja 0077 - Chiriguaná Norte 4", codigo_sun_factory="COLCEST60P2",
        portafolio="Skandia",
        inversionista_nombre="PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A.",
        estado="vigente", tarifa_admin=0.038, tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
        indexacion_representacion=[
            {"año": 2024, "ipc": None, "valor": 6.0, "esBase": True},
            {"año": 2025, "ipc": 5.2,  "valor": 6.312},
            {"año": 2026, "ipc": 5.1,  "valor": 6.633912},
        ],
    ),
    # ── GD Marimonda ────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Marimonda", inversionista_nombre="LA HORMIGA SOLAR S.A.S. E.S.P.",
        estado="vigente", fecha_firma_contrato="2025-03-17",
        enlace_drive="https://drive.google.com/file/d/1uUIroNjUcCJdNiqcSpu3LRV3a7n8yDgH/view?usp=drive_link",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── MGS Naos 2 ──────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="MGS Naos 2", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
        estado="vigente", fecha_firma_contrato="2025-02-20",
        enlace_drive="https://drive.google.com/file/d/1Rjy0dVYdqcHsVU6tDtM7JQdXGdY8wMzg/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── MGS Naos 3 ──────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="MGS Naos 3", inversionista_nombre="GD EL REMOLINO 1 S.A.S. E.S.P",
        estado="vigente", fecha_firma_contrato="2025-04-04",
        enlace_drive="https://drive.google.com/file/d/1E7BQ5LzLs0vKNXQKJ1QfxbEOV6R9Qsjl/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── Bayunca ─────────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Bayunca", inversionista_nombre="PARQUE EOLICO DE GALERAZAMBA S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-04-07",
        enlace_drive="https://drive.google.com/file/d/1BHe5yoiPT9t-tBIJCLnKbREvtscu7PHx/view?usp=sharing",
        tarifa_cgm=0.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 0.0, "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 0.0},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD Delta 1 ──────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Delta 1", inversionista_nombre="GRANJAS SOLARES DELTA S.A.S. E.S.P",
        estado="vigente", fecha_firma_contrato="2025-06-11",
        enlace_drive="https://drive.google.com/file/d/1JD8jRf8UUs9PwVDpStfcF2XuCerHQyVh/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── GD Polaris 1 ────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Polaris 1", inversionista_nombre="GRANJA SOLAR POLARIS ENERGY S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-06-11",
        enlace_drive="https://drive.google.com/file/d/1dbTdzyy0v5nepdtILhwcYIODp8a0eoZJ/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── GD Sirius ───────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Sirius", inversionista_nombre="QUANTUM ENERGY INGENIERÍA S.A.S",
        estado="vigente", fecha_firma_contrato="2025-06-09",
        enlace_drive="https://drive.google.com/file/d/1KcgA0iKTJWkiWBp1h6EAg0CArVijcUL3/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD Biosolar ─────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Biosolar", inversionista_nombre="INVERSIONES BIOSOSTENIBLES S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-06-09",
        enlace_drive="https://drive.google.com/file/d/10eR0HhJZu2SQn0h8UIhGtdUox3bXcZOU/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD Astrolumen La Garita ─────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Astrolumen La Garita", inversionista_nombre="Energy Investment Group SAS",
        estado="vigente", fecha_firma_contrato="2025-06-09",
        enlace_drive="https://drive.google.com/file/d/1Wo6gmts3B1JXMlDtBVfOP88MgzDqrNP_/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD Agustin 1 ────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Agustin 1", inversionista_nombre="FONSAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-06-09",
        enlace_drive="https://drive.google.com/file/d/1dRZdu-aiRFC9ghULWok9SzGu79XFw47V/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD 1MVA SAN ONOFRE ──────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD 1MVA SAN ONOFRE", inversionista_nombre="NOVAVALOR ENERGY SAS",
        estado="vigente", fecha_firma_contrato="2025-07-12",
        enlace_drive="https://drive.google.com/file/d/1HgFGQzBVE51WtdQkt3KvQ9Sgav1dZQhH/view?usp=sharing",
        tarifa_cgm=0.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 0.0, "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 0.0},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD Yuan Solar ───────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Yuan Solar", inversionista_nombre="FEM ENERGÍA S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-08-09",
        enlace_drive="https://drive.google.com/file/d/12SUYJsDy3K7WmNjN-l0CKYzPqLq9p9PO/view?usp=sharing",
        tarifa_cgm=5.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.255},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── La Catedral ─────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="La Catedral", inversionista_nombre="PELLETCO S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-08-22",
        enlace_drive="https://drive.google.com/file/d/1NOxvjvr8Zo6lISXvZj1Ap8KGUjcOfAFt/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD delta 2 ──────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD delta 2", inversionista_nombre="GRANJAS SOLARES DELTA S.A.S. E.S.P",
        estado="vigente", fecha_firma_contrato="2025-08-25",
        enlace_drive="https://drive.google.com/file/d/1arn43qJMevk8nSCbHpdyDprO24ekseNQ/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── PSF - Yurbaqua ──────────────────────────────────────────────────────
    dict(
        proyecto_nombre="PSF - Yurbaqua", inversionista_nombre="ENEXA ENERGY S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-08-20",
        enlace_drive="https://drive.google.com/file/d/1D2F-_DM9UB5iLzL6wAeYA_03q6XHAzlu/view?usp=sharing",
        tarifa_cgm=5.0, tarifa_representacion=5.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.255},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 5.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.255},
        ],
    ),
    # ── GD Polaris 2 ────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Polaris 2", inversionista_nombre="GRANJA SOLAR POLARIS 2 S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-09-02",
        enlace_drive="https://drive.google.com/file/d/1Al9HvwvdGeC3tJGxc9S1UaJeU-0sr2Yo/view?usp=sharing",
        tarifa_cgm=7.0, tarifa_representacion=3.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 7.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 7.357},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 3.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 3.153},
        ],
    ),
    # ── GD San Pelayo ───────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD San Pelayo", inversionista_nombre="SAMBA SOLAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-09-05",
        enlace_drive="https://drive.google.com/file/d/1M9xdHMsjPan5unAiI01elbvWkB9oz4WN/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── Monterrey ───────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Monterrey", inversionista_nombre="EXTRACTORA MONTERREY S.A.S",
        estado="vigente", fecha_firma_contrato="2025-10-17",
        enlace_drive="https://drive.google.com/file/d/1XpkmrCBtXP1-G84VHI7VI8uk897WG1ts/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── Sol Y Cielo 7 Los Bongos ────────────────────────────────────────────
    dict(
        proyecto_nombre="Sol Y Cielo 7 Los Bongos", inversionista_nombre="INENERGY S.A.S",
        estado="vigente", fecha_firma_contrato="2025-11-19",
        enlace_drive="https://drive.google.com/file/d/1Y4X_uqmtI6Xr9fizffVYHkIngnaiwyQa/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── GD La Hormiga ───────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD La Hormiga", inversionista_nombre="BALI ENERGY S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-11-19",
        enlace_drive="https://drive.google.com/file/d/1VowW9ZZqlW96GQ7d8UxzsIZ8m7fpRMqq/view?usp=drive_link",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
    ),
    # ── Sol&Cielo 9 - Ciénaga ───────────────────────────────────────────────
    dict(
        proyecto_nombre="Sol&Cielo 9 - Ciénaga", inversionista_nombre="INENERGY S.A.S",
        estado="vigente", fecha_firma_contrato="2025-11-19",
        enlace_drive="https://drive.google.com/file/d/1L0MbDmQF5VE53Z03o3yDSNeXLy1Qqzf0/view?usp=drive_link",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 6.0,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 6.306},
        ],
    ),
    # ── Taurus VIII/IX/X ────────────────────────────────────────────────────
    dict(
        proyecto_nombre="Taurus VIII", inversionista_nombre="CUMBIA SOLAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-12-22",
        enlace_drive="https://drive.google.com/file/d/1K1WyQqXsE1v2Vr_RIuJdt-6ZbvaI1Tfq/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
    ),
    dict(
        proyecto_nombre="Taurus IX", inversionista_nombre="FLAUTA SOLAR SAS",
        estado="vigente", fecha_firma_contrato="2025-12-22",
        enlace_drive="https://drive.google.com/file/d/14u3Wf7fAP7EmtYInWP6N9UP1YDcH3XwK/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
    ),
    dict(
        proyecto_nombre="Taurus X", inversionista_nombre="ACORDEON SOLAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2025-12-22",
        enlace_drive="https://drive.google.com/file/d/13JqZAxX_HI0G3WRCp5mL9FraSSdnPr52/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
        indexacion_representacion=[
            {"año": 2025, "ipc": None, "valor": 5.5,     "esBase": True},
            {"año": 2026, "ipc": 5.1,  "valor": 5.7805},
        ],
    ),
    # ── 2026 ────────────────────────────────────────────────────────────────
    dict(
        proyecto_nombre="GD Garza", inversionista_nombre="PULOI SOLAR S.A.S",
        estado="vigente", fecha_firma_contrato="2026-01-22",
        enlace_drive="https://drive.google.com/file/d/1nXWG8ZiwUVZm9LcwydXU7IcDAyuLICU8/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
    ),
    dict(
        proyecto_nombre="La Perdiz", inversionista_nombre="MONOCUCO SOLAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2026-01-22",
        enlace_drive="https://drive.google.com/file/d/1vT2OAng0d5SgXMJXFsARBHVTTodf3uyE/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
    ),
    dict(
        proyecto_nombre="GD El Mandarino", inversionista_nombre="LAS FAROTAS SOLAR S.A.S",
        estado="vigente", fecha_firma_contrato="2026-02-03",
        enlace_drive="https://drive.google.com/file/d/1ogA7nVDa4muew6s1aeh3CuXJdZN8MRJE/view?usp=sharing",
        tarifa_cgm=5.5, tarifa_representacion=5.5,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 5.5, "esBase": True}],
    ),
    dict(
        proyecto_nombre="GD Isabela", inversionista_nombre="JHON JAIME CASTRO CHAPARRO",
        estado="vigente", fecha_firma_contrato="2026-02-13",
        enlace_drive="https://drive.google.com/file/d/1Bs870ApgaiXu8oX2c-7MiuH20Mx71ipk/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
    ),
    dict(
        proyecto_nombre="GD ELEKTRA", inversionista_nombre="QUANTUM ENERGY INGENIERIA S.A.S",
        estado="vigente", fecha_firma_contrato="2026-03-12",
        enlace_drive="https://drive.google.com/file/d/1ha7tiY1QEgU99SvgxWqxW75BAbI49Pz9/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
    ),
    dict(
        proyecto_nombre="Agustín 2", inversionista_nombre="FONSAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2026-03-12",
        enlace_drive="https://drive.google.com/file/d/1OIO4dGe1Dqi-5fa4ZWaAE8lyUZSmiX9K/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
    ),
    dict(
        proyecto_nombre="Agustín 3", inversionista_nombre="FONSAR S.A.S.",
        estado="vigente", fecha_firma_contrato="2026-03-12",
        enlace_drive="https://drive.google.com/file/d/1tHc1YpqCgeKOfa77F18OxNRR0XfmWp1t/view?usp=sharing",
        tarifa_cgm=6.0, tarifa_representacion=6.0,
        indexacion_cgm=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
        indexacion_representacion=[{"año": 2026, "ipc": None, "valor": 6.0, "esBase": True}],
    ),
    # ── MGS 0011 El Roble ───────────────────────────────────────────────────
    dict(
        proyecto_nombre="MGS 0011 El Roble",
        inversionista_nombre="PROMOTORA DE ENERGIA ELECTRICA DE CARTAGENA S.A.S E.S.P.",
        estado="vigente", tarifa_cgm=6.0,
        indexacion_cgm=[{"año": 2024, "ipc": None, "valor": 6.0, "esBase": True}],
        indexacion_representacion=[],
    ),
]


def _find_proyecto_id(db, nombre: str):
    from sqlalchemy import text
    r = db.execute(
        text("SELECT id FROM proyectos WHERE LOWER(nombre_comercial) LIKE LOWER(:q) LIMIT 1"),
        {"q": f"%{nombre}%"}
    ).first()
    return r[0] if r else None


def main():
    db = SessionLocal()
    try:
        insertados = 0
        sin_proyecto = []
        for c in CONTRATOS:
            nombre = c.pop("proyecto_nombre")
            proyecto_id = _find_proyecto_id(db, nombre)
            if not proyecto_id:
                sin_proyecto.append(nombre)

            fecha_str = c.pop("fecha_firma_contrato", None)
            from datetime import date
            fecha = date.fromisoformat(fecha_str) if fecha_str else None

            obj = ContratoServicio(
                proyecto_id=proyecto_id,
                servicio_aplica="representacion",
                contratante_nombre="Unergy Energía Digital S.A.S. E.S.P.",
                prestador_nombre="Unergy Energía Digital S.A.S. E.S.P.",
                fecha_firma_contrato=fecha,
                **c,
            )
            db.add(obj)
            insertados += 1

        db.commit()
        print(f"✓ {insertados} contratos insertados")
        if sin_proyecto:
            print(f"⚠ Sin proyecto encontrado para: {sin_proyecto}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
