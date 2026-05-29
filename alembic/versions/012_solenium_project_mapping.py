"""Map proyectos to their Solenium project IDs (initial seed)

Adds project_id_solenium column if missing (idempotent) and seeds
the 49 known project→Solenium-ID mappings discovered by cross-referencing
our 88 DB projects with the 76 projects returned by the Solenium API.

Revision ID: 012
Revises: 011
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Ensure column exists (idempotent — create_all may have already added it)
    op.execute(
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS project_id_solenium VARCHAR(100)"
    )

    # 2. Seed the known Solenium ↔ DB project mappings.
    #    Each row: (solenium_id, our db proyecto.id)
    #    Only update if not already set (to be safe on re-runs).
    mappings = [
        # Minigranja (MGS) projects — our "MGS XXXX Name" = Solenium "Minigranja XXXX - Name"
        ("122", 49),   # Minigranja Solar Uruaco        → Minigranja 0001 - Uruaco
        ("136", 4),    # Minigranja Solar Baraya        → Minigranja 0002 - Baraya
        ("118", 45),   # Minigranja Solar San Pedro     → Minigranja 0003 - San Pedro
        ("130", 22),   # MGS 0004 Valle de Gandalf      → Minigranja 0004 - Gandalf
        ("108", 10),   # MGS 0005 Cañahuate             → Minigranja 0005 - Cañahuate
        ("144", 36),   # MGS 0006 Perija                → Minigranja 0006 - Perija
        ("127", 52),   # MGS 0007 La Paz Vallenata      → Minigranja 0007 - La Paz Vallenata
        ("113", 53),   # MGS 0008 La Paz Verso          → Minigranja 0008 - La Paz Verso
        ("143", 20),   # MGS 0009 El Molino             → Minigranja 0009 - El Molino
        ("149", 54),   # MGS 0010 Villanueva            → Minigranja 0010 - Villanueva
        ("150", 1),    # MGS 0012 La Reserva            → Minigranja 0012 - La Reserva
        ("157", 27),   # MGS 0013 La Mesa               → Minigranja 0013 - La Mesa
        ("153", 35),   # MGS 0014 El Olimpo             → Minigranja 0014 - El Olimpo
        ("146", 24),   # Minigranja Solar El Son        → Minigranja 0015 - El Son
        ("148", 40),   # MGS 0016 Puya                  → Minigranja 0016 - La Puya
        ("147", 21),   # MGS 0017 Esmeralda             → Minigranja 0017 - La Paz Esmeralda
        ("102", 31),   # MGS 0018 La Paz Leyenda        → Minigranja 0018 - La Paz Leyenda
        ("145", 25),   # MGS 0019 El Merengue           → Minigranja 0019 - El Merengue
        ("176", 28),   # MGS Mapale                     → Minigranja 0020 - El Mapalé
        ("154", 23),   # MGS 0021 Ibirico               → Minigranja 0021 - Ibirico
        ("160", 17),   # MGS 0022 La Cumbia             → Minigranja 0022 - La Cumbia
        ("156", 26),   # MGS 0023 Joropo                → Minigranja 0023 - Joropo
        ("159", 42),   # MGS 0024 San Diego Sur         → Minigranja 0024 - San Diego Sur
        ("168", 16),   # MGS 0025 El Copey Occidente    → Minigranja 0025 - El Copey
        ("162", 51),   # MGS 0026 Valencia Oriente 1    → Minigranja 0026 - Valencia Or_1
        ("161", 50),   # MGS 0027 Valencia Oriente 2    → Minigranja 0027 - Valencia Or_2
        ("167", 91),   # MGS 0028 Chiriguana N1         → Minigranja 0028 - Chiriguaná N1
        ("165", 8),    # MGS 0040 Cacica                → Minigranja 0040 - La Cacica
        ("166", 37),   # MGS 0041 Piloneras             → Minigranja 0041 - Las Piloneras
        ("174", 13),   # MGS 0075 Chiriguana Norte 2    → Minigranja 0075 - Chiriguaná N2
        ("173", 14),   # MGS 0077 Chiriguana Norte 4    → Minigranja 0077 - Chiriguaná N4
        # C&I / commercial projects (name-matched)
        ("100", 66),   # AMC                            → AMC
        ("101", 86),   # Arboleda Castilla              → Arboleda de Castilla
        ("141", 64),   # Acanto                         → Condominio Acanto
        ("111", 57),   # Cedillanos                     → Cedillanos
        ("138", 76),   # IBES                           → IBES
        ("115", 62),   # IML Empaques                   → IML Empaques
        ("119", 71),   # Coopsana Sub Proyecto 1        → IPS Coopsana
        ("107", 63),   # Los Coches                     → Hotel Los Coches
        ("140", 60),   # Maderas                        → Central de Maderas
        ("137", 73),   # MDM                            → MDM Científica
        ("158", 59),   # Nestlé                         → Nestlé DPA
        ("123", 72),   # Pola del Pub                   → Pola del Pub
        ("105", 78),   # San Angelo                     → Gimnasio San Ángelo
        ("120", 61),   # Salud Vegas                    → Salud Vegas
        ("133", 74),   # San Simón                      → San Simon
        ("139", 69),   # Seridme                        → SERIDME
        ("131", 68),   # Almagran                       → Torre Almagrán
    ]

    for sol_id, db_id in mappings:
        op.execute(
            f"UPDATE proyectos SET project_id_solenium='{sol_id}' "
            f"WHERE id={db_id} AND project_id_solenium IS NULL"
        )


def downgrade() -> None:
    # Clear the seeded values (does not drop the column)
    db_ids = [
        49, 4, 45, 22, 10, 36, 52, 53, 20, 54, 1, 27, 35, 24, 40, 21,
        31, 25, 28, 23, 17, 26, 42, 16, 51, 50, 91, 8, 37, 13, 14,
        66, 86, 64, 57, 76, 62, 71, 63, 60, 73, 59, 72, 78, 61, 74, 69, 68,
    ]
    ids_str = ", ".join(str(i) for i in db_ids)
    op.execute(f"UPDATE proyectos SET project_id_solenium=NULL WHERE id IN ({ids_str})")
