"""fronteras: eliminar municipio (duplicaba Proyecto.municipio)

Auditoria de calidad de datos de Fronteras (2026-08-25). 47/69 (68%)
coincidian donde ambos tenian dato -- las diferencias eran casi todas de
formato/nivel de detalle ("Cucuta" vs "Cucuta" con tilde, "L.Jagua
Ibirico" vs "La Jagua de Ibirico", corregimiento vs municipio). Sara
decidio: vive en Proyecto, Frontera se alimenta de ahi -- mismo patron
que potencia_instalada_kwp/departamento/tipo_tecnologia.

Antes de eliminar: 16 proyectos no tenian su propio municipio y se
habrian quedado sin dato -- se rellenan con el valor que ya tenia su(s)
frontera(s) (coincidente entre las fronteras del mismo proyecto en los
16 casos, sin conflicto que resolver).

Los 16 valores se validaron contra el catalogo DIVIPOLA que ya usa
ProyectoForm.vue (src/data/colombia-divipola.json, un Select real en vez
de texto libre) -- 14 coincidian tal cual; 2 no por ortografia/tildes
("Cienaga de Oro" -> "Ciénaga de Oro", Córdoba; "Barranca de Upia" ->
"Barranca de Upía", Meta) y se corrigen aca para que el proyecto quede
seleccionable en el dropdown sin que aparezca vacio. "San Cayetano"
existe en 2 departamentos (Cundinamarca y Norte de Santander) --
desambiguado con las coordenadas de la propia frontera (7.72-7.88°N,
-72.55°O, dentro de Norte de Santander) antes de confirmar el
departamento en la migracion 091.

Revision ID: 092
Revises: 091
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None

_BACKFILL = {
    3: "Los Patios",
    6: "San Cayetano",
    7: "Tierralta",
    15: "Ciénaga de Oro",
    18: "Taminango",
    29: "Galapa",
    32: "Taminango",
    33: "Taminango",
    34: "Taminango",
    38: "Mercaderes",
    39: "Mercaderes",
    44: "San Pelayo",
    46: "San Cayetano",
    55: "Barranca de Upía",
    56: "Turbaco",
    84: "Sabanagrande",
}


def upgrade():
    conn = op.get_bind()
    for proyecto_id, municipio in _BACKFILL.items():
        conn.execute(
            sa.text("UPDATE proyectos SET municipio = :m WHERE id = :id AND municipio IS NULL"),
            {"m": municipio, "id": proyecto_id},
        )
    op.drop_column("fronteras", "municipio")


def downgrade():
    op.add_column("fronteras", sa.Column("municipio", sa.String(length=100), nullable=True))
