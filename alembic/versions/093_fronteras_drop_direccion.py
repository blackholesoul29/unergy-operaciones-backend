"""fronteras: eliminar direccion (consolidada en Proyecto.direccion_vereda)

Auditoria de calidad de datos de Fronteras (2026-08-25). A diferencia de
municipio/departamento/tipo_tecnologia/potencia, direccion NO coincidia
textualmente con Proyecto.direccion_vereda (0/45 identicas donde ambas
tenian dato) -- son dos transcripciones independientes del mismo sitio,
sin que una fuera consistentemente mas completa (25/45 Proyecto mas
larga, 20/45 Frontera). Sin uso de logica de negocio en ningun lado
(ni siquiera el volcado de comercial.py la incluia), solo de solo
lectura en FronteraDetailView.vue. Sara decidio: Proyecto.direccion_vereda
gana siempre de aca en adelante, igual que los demas campos de ubicacion.

Antes de eliminar: 27 proyectos no tenian su propia direccion y se
habrian quedado sin dato -- se rellenan con la de su(s) frontera(s). 6
de esos 27 tenian direcciones ligeramente distintas entre las fronteras
del mismo proyecto (variantes del import de GESCON, mismo sitio con un
sufijo de zona distinto -- "VIA"/"VEREDA"/"ZONA") -- se usa la mas larga
como criterio de desempate simple.

Revision ID: 093
Revises: 092
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None

_BACKFILL = {
    2: "SECTOR VEREDA PATILLARES CORREGIMIENTO EL SALADO, LOTE 2, SAN JOSE DE CUCUTA VEREDA",
    3: "SECTOR CLUB DE ALCAZAR PARCELA 5, LA GARITA, LOS PATIOS NORTE DE SANTANDER ZONA",
    5: "CORREGIMIENTO BAYUNCA",
    6: "CLUB DE ALCAZAR PARCELA 5, LA GARITA, LOS PATIOS NORTE DE SANTANDER ZONA",
    7: "SECTOR H.DA LOS BONGOS, VARIANTE URRA HACIENDA",
    11: "BODEGA km 89 VIA A L Yarumal - Antioquia VEREDA",
    13: "SECTOR via curumaní - Bosconia(ruta del sol sector 3) VEREDA",
    14: "SECTOR via curumaní - Bosconia(ruta del sol sector 3) ZONA",
    15: "SECTOR calle 2# 7 - 455 VIA",
    18: "SECTOR DEL Lote la esperanza, Vereda El Lecheral, Vía Pasto - Mojarras km 80 500 VIA",
    28: "SECTOR Predio Rural, Vía a la vereda Valledupar, Valledupar VIA",
    29: "SECTOR PR 13 DE LA CIRCUNVALAR DE LA PROSPERIDAD VEREDA",
    32: "Vereda el recod",
    33: "SECTOR Vereda el Recodo, Corregimiento El Remolino (Nariño) VEREDA",
    34: "Vereda el recodo, corregimieto de El Remolino (Nariño)",
    36: "Via San Diego Las Pitillas Kilometro 7",
    37: "SECTOR vereda globo la vega arriba, Valledupar VEREDA",
    38: "CONDOMINIO Condominio Ciudad Solar, km 91 vía Pasto-Mojarras VIA",
    39: "SECTOR Condominio Ciudad Solar, km 91 vía Pasto-Mojarras HACIENDA",
    40: "SECTOR Predio Jericó 7, Vía Valledupar - Villanueva, municipio Valledupar VIA",
    43: "SECTOR a 130 metros de la S.E. AFINIA SAN ONOFRE_CALLE 27 A CRA 24 CARRETERA",
    44: "SECTOR San Pelayo, Córdoba VEREDA",
    46: "SECTOR LOTE 2, VEREDA SAN ISIDRO, SAN CAYETANO, NORTE DE SANTANDER TRONCAL",
    50: "SECTOR vía valledupar- Vereda Los Calabozos, valedupar, Cesar VEREDA",
    55: "SECTOR 4.562810, -73.041811, Barranca de Upía, Meta ZONA",
    56: "CALLE 1 # 2-5 SECTOR ZONA FRANCA PARQUE CENTRAL variante turbaco sector aguas prietas VARIANTE",
    84: "Sabanagrande, atlántico.",
}


def upgrade():
    conn = op.get_bind()
    for proyecto_id, direccion in _BACKFILL.items():
        conn.execute(
            sa.text("UPDATE proyectos SET direccion_vereda = :d WHERE id = :id AND direccion_vereda IS NULL"),
            {"d": direccion, "id": proyecto_id},
        )
    op.drop_column("fronteras", "direccion")


def downgrade():
    op.add_column("fronteras", sa.Column("direccion", sa.String(length=500), nullable=True))
