"""fronteras: eliminar latitud/longitud/altitud_msnm, consolidados en Proyecto

Auditoria de calidad de datos de Fronteras (2026-08-25). A diferencia de
los demas campos de ubicacion, latitud/longitud NO eran mas confiables
en ninguna de las dos tablas -- ambas mostraban el mismo vicio (varios
proyectos DISTINTOS y reales compartiendo exactamente la misma
coordenada hasta el sexto decimal, seguramente un punto aproximado
reusado en vez del GPS real de cada sitio). Proyecto.latitud/longitud
son campos de texto libre en ProyectoForm.vue, sin ningun catalogo que
los valide. altitud_msnm no tenia NINGUN equivalente en Proyecto -- se
agrega la columna.

Se confirmo que el sync de Sun Factory (tsf_sync.py, COALESCE sobre
municipio/departamento/latitud/longitud/potencia_instalada_kwp, nunca
pisa un dato existente) no compite con este backfill: ninguno de los 19
proyectos que necesitan latitud/longitud propia tiene
sunfactory_project_id, y ese sync ni siquiera toca altitud_msnm.

Sara pidio explicitamente una proteccion en Proyecto para que este mismo
problema no se repita con registros futuros -- se trasladan los mismos
CHECK que tenia Frontera (rango valido de lat/lon) y se agrega uno nuevo
para altitud_msnm (0-5800 msnm es el rango real de Colombia, se usa
-100..6000 para no bloquear variacion real). Verificado contra los 145
proyectos existentes: 0 filas violarian estos rangos.

Backfill de latitud/longitud (19 proyectos sin dato propio -- los que
ya tenian el suyo NO se tocan, ganan ellos):
- 17 casos: promedio simple entre sus fronteras (identico o redondeo
  trivial en la mayoria).
- Proyecto 33 (MGS Naos 2): sus 2 fronteras traian longitud -77.33988 y
  -73.33988 -- un digito de la longitud cambiado, salto de 4 grados
  geograficamente imposible dentro del mismo cluster de Naos 1/2/3 en
  Nariño (todos alrededor de -77.3). Se usa -77.33988.

Backfill de altitud_msnm (50 proyectos -- TODOS, la columna no existia):
- 48 casos: promedio simple, redondeado al metro. La mayoria de las
  fronteras del mismo proyecto difieren por 1-15m, ruido normal de GPS.
- Proyecto 20 (MGS 0009 El Molino): 810 vs 196 -- 614m de diferencia,
  no es ruido. El valor 810 esta asociado a una coordenada redondeada/
  generica (10.700000, -72.950000); el 196 a la coordenada real y mas
  precisa de esa misma frontera (10.704000, -72.958626). Se usa 196.
- Proyecto 26 (MGS 0023 El Joropo): 373 vs 128 -- mismo caso de las
  fronteras a ~21km de diferencia ya detectado para latitud/longitud en
  esta auditoria. El valor 128 va con la coordenada cercana a Valledupar
  (plausible); 373 con la que ya estaba senalada como sospechosa. Se
  usa 128.

Revision ID: 094
Revises: 093
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None

_BACKFILL_LATLON = {
    2: (7.985638, -72.504604),
    3: (7.71971, -72.548133),
    5: (10.532254, -75.394769),
    6: (7.720244, -72.547921),
    7: (8.17083, -76.041521),
    11: (6.81, -75.49),
    15: (8.908244, -75.740836),
    18: (1.634333, -77.334444),
    29: (10.898475, -74.857188),
    32: (1.666, -77.343),
    33: (1.66577, -77.33988),
    34: (1.66577, -77.33988),
    38: (1.680719, -77.31536),
    39: (1.681587, -77.316065),
    44: (8.976824, -75.820159),
    46: (7.876085, -72.546483),
    55: (4.56281, -73.041811),
    56: (10.3894, -75.4461),
    84: (10.794297, -74.759763),
}

_BACKFILL_ALTITUD = {
    1: 117, 2: 256, 3: 589, 4: 52, 5: 35, 6: 310, 7: 55, 8: 268, 9: 160,
    10: 116, 11: 2776, 13: 46, 14: 46, 15: 7, 16: 104, 17: 130, 18: 845,
    20: 196, 21: 145, 22: 115, 23: 75, 24: 110, 25: 134, 26: 128, 27: 1145,
    28: 131, 29: 75, 31: 122, 32: 484, 33: 493, 34: 500, 35: 1241, 36: 112,
    37: 268, 38: 613, 39: 614, 40: 126, 42: 116, 43: 43, 44: 6, 46: 255,
    49: 56, 50: 114, 51: 112, 52: 122, 53: 122, 54: 230, 55: 200, 56: 20,
    84: 25,
}


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_checks = {
        c["name"] for c in inspector.get_check_constraints("proyectos")
    }

    # Idempotente: un parche de emergencia (commit 8c9551b, Jessica) ya habia
    # agregado esta columna + su CHECK en produccion el mismo dia, porque el
    # modelo la declaraba antes de que esta migracion llegara a correr (la
    # cadena de Alembic estaba atascada en 082 por el problema de
    # 085_contrato_frontera). Ese parche tambien rellenO altitud_msnm para
    # los 50 proyectos usando "la frontera de menor id" -- sin el criterio de
    # plausibilidad geografica aplicado aca, asi que los proyectos 20 y 26
    # (ver _BACKFILL_ALTITUD) se corrigen explicitamente mas abajo aunque ya
    # tengan dato, en vez de respetar el WHERE ... IS NULL como el resto.
    existing_columns = {c["name"] for c in inspector.get_columns("proyectos")}
    if "altitud_msnm" not in existing_columns:
        op.add_column("proyectos", sa.Column("altitud_msnm", sa.Integer(), nullable=True))
    if "ck_proyectos_latitud_rango" not in existing_checks:
        op.create_check_constraint(
            "ck_proyectos_latitud_rango",
            "proyectos", "latitud IS NULL OR (latitud >= -90 AND latitud <= 90)",
        )
    if "ck_proyectos_longitud_rango" not in existing_checks:
        op.create_check_constraint(
            "ck_proyectos_longitud_rango",
            "proyectos", "longitud IS NULL OR (longitud >= -180 AND longitud <= 180)",
        )
    if "ck_proyectos_altitud_msnm_rango" not in existing_checks:
        op.create_check_constraint(
            "ck_proyectos_altitud_msnm_rango",
            "proyectos", "altitud_msnm IS NULL OR (altitud_msnm >= -100 AND altitud_msnm <= 6000)",
        )

    _CORRECCIONES_PLAUSIBILIDAD = {20, 26}
    for proyecto_id, (lat, lon) in _BACKFILL_LATLON.items():
        conn.execute(
            sa.text(
                "UPDATE proyectos SET latitud = :lat, longitud = :lon "
                "WHERE id = :id AND latitud IS NULL"
            ),
            {"lat": lat, "lon": lon, "id": proyecto_id},
        )
    for proyecto_id, altitud in _BACKFILL_ALTITUD.items():
        clausula_id = "" if proyecto_id in _CORRECCIONES_PLAUSIBILIDAD else " AND altitud_msnm IS NULL"
        conn.execute(
            sa.text(f"UPDATE proyectos SET altitud_msnm = :a WHERE id = :id{clausula_id}"),
            {"a": altitud, "id": proyecto_id},
        )

    op.drop_column("fronteras", "latitud")
    op.drop_column("fronteras", "longitud")
    op.drop_column("fronteras", "altitud_msnm")


def downgrade():
    op.add_column("fronteras", sa.Column("altitud_msnm", sa.Integer(), nullable=True))
    op.add_column("fronteras", sa.Column("longitud", sa.Numeric(9, 6), nullable=True))
    op.add_column("fronteras", sa.Column("latitud", sa.Numeric(9, 6), nullable=True))
    op.create_check_constraint(
        "ck_fronteras_longitud_rango",
        "fronteras", "longitud IS NULL OR (longitud >= -180 AND longitud <= 180)",
    )
    op.create_check_constraint(
        "ck_fronteras_latitud_rango",
        "fronteras", "latitud IS NULL OR (latitud >= -90 AND latitud <= 90)",
    )
    op.drop_constraint("ck_proyectos_altitud_msnm_rango", "proyectos", type_="check")
    op.drop_constraint("ck_proyectos_longitud_rango", "proyectos", type_="check")
    op.drop_constraint("ck_proyectos_latitud_rango", "proyectos", type_="check")
    op.drop_column("proyectos", "altitud_msnm")
