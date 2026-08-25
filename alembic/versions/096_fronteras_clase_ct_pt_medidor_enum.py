"""fronteras: clase_ct/clase_pt/clase_medidor pasan a Enum real

Auditoria de calidad de datos de Fronteras (2026-08-25). Eran texto libre
sin validar y sin ningun desplegable para cargarlas -- ni siquiera eran
editables en el frontend. Datos actuales ya limpios y acotados a un set
chico de clases de precision de metrologia (CREG, fronteras comerciales):

- clase_ct: '0.2' (2), '0.2s' (6), '0.5s' (86)
- clase_pt: '0.2' (6), '0.5' (88)
- clase_medidor: '0.2s' (2), '0.5s' (92)

Sara pidio explicitamente acotar el enum a las clases YA en uso, no al
catalogo completo de la norma -- si hace falta una clase nueva, se agrega
puntualmente. Migracion de solo-tipo (ALTER COLUMN ... USING ...::enum),
sin backfill: los valores actuales ya son compatibles 1:1 con el enum.

Revision ID: 096
Revises: 095
Create Date: 2026-08-25
"""
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None

_CLASE_CT = postgresql.ENUM("0.2", "0.2s", "0.5s", name="clase_ct_enum")
_CLASE_PT = postgresql.ENUM("0.2", "0.5", name="clase_pt_enum")
_CLASE_MEDIDOR = postgresql.ENUM("0.2s", "0.5s", name="clase_medidor_enum")


def upgrade():
    bind = op.get_bind()
    _CLASE_CT.create(bind, checkfirst=True)
    _CLASE_PT.create(bind, checkfirst=True)
    _CLASE_MEDIDOR.create(bind, checkfirst=True)

    op.execute("ALTER TABLE fronteras ALTER COLUMN clase_ct TYPE clase_ct_enum USING clase_ct::clase_ct_enum")
    op.execute("ALTER TABLE fronteras ALTER COLUMN clase_pt TYPE clase_pt_enum USING clase_pt::clase_pt_enum")
    op.execute(
        "ALTER TABLE fronteras ALTER COLUMN clase_medidor TYPE clase_medidor_enum "
        "USING clase_medidor::clase_medidor_enum"
    )


def downgrade():
    op.execute("ALTER TABLE fronteras ALTER COLUMN clase_ct TYPE VARCHAR(20) USING clase_ct::text")
    op.execute("ALTER TABLE fronteras ALTER COLUMN clase_pt TYPE VARCHAR(20) USING clase_pt::text")
    op.execute("ALTER TABLE fronteras ALTER COLUMN clase_medidor TYPE VARCHAR(50) USING clase_medidor::text")

    bind = op.get_bind()
    _CLASE_CT.drop(bind, checkfirst=True)
    _CLASE_PT.drop(bind, checkfirst=True)
    _CLASE_MEDIDOR.drop(bind, checkfirst=True)
