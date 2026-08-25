"""elimina liquidacion_xm_datos: subsistema muerto, superado por Panel Contable

Investigacion pedida por Sara sobre las tablas conectadas a `fronteras`
(2026-08-25). `liquidacion_xm_datos` no encajaba en el criterio original
("si solo esta asociada a fronteras, eliminar") -- tiene DOS FK,
`liquidacion_id` (NOT NULL, obligatoria) y `frontera_id` (nullable) -- es
una tabla hija de `liquidaciones`, no de `fronteras`. Se investigo aparte
y se confirmo que de todas formas esta muerta:

- 0 filas (y `liquidaciones.ingresos_energia_cop`, el campo resumen que
  alimentaria via el endpoint auto-populate, tambien esta en 0/444).
- El backend tenia CRUD completo (`POST/PATCH/DELETE
  /liquidaciones/{id}/xm-datos/{dato_id}`) mas un endpoint de
  auto-poblado (`POST .../xm-datos/auto-populate`, agregado 2026-08-13)
  que suma generacion_diaria + precio de bolsa/PPA -- pero el frontend
  nunca llamo ninguno de esos endpoints (grep de "xm-datos"/"xm_datos"
  en unergy-operaciones-frontend/src: 0 resultados).
- Confirmado el reemplazo real: `panel_contable_linea` (grupo='ingresos',
  6052 filas pobladas, con conceptos reales como "Ingreso Bruto Terpel",
  "Venta en bolsa") es la fuente que efectivamente usa
  `GET /liquidaciones/resumen-panel` -- el propio docstring de ese
  endpoint ya decia "el Estado de Resultados... es espejo del Panel
  Contable". liquidacion_xm_datos quedo de un diseño anterior, nunca
  conectado al frontend, superado por el Panel Contable.

Se elimina: la tabla, el modelo `LiquidacionXMDato`, los 5 endpoints
(incluido auto-populate), los schemas XMDatoCreate/XMDatoUpdate, y el
`relationship` en ambos lados (`Liquidacion.xm_datos`,
`Frontera.xm_datos`). La tabla nunca la creo una migracion de Alembic
-- solo existia via el mecanismo legacy `_PENDING_DDLS`/
`_run_column_migrations()` en app/main.py (ya limpiado en el mismo
commit que esta migracion).

Idempotente por el mismo motivo que las migraciones recientes de esta
sesion: alembic upgrade head no siempre corre limpio en el deploy de
Railway.

Revision ID: 098
Revises: 097
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("liquidacion_xm_datos"):
        op.drop_table("liquidacion_xm_datos")


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("liquidacion_xm_datos"):
        op.create_table(
            "liquidacion_xm_datos",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("liquidacion_id", sa.BigInteger(), sa.ForeignKey("liquidaciones.id"), nullable=False, index=True),
            sa.Column("frontera_id", sa.BigInteger(), sa.ForeignKey("fronteras.id", ondelete="RESTRICT"), nullable=True, index=True),
            sa.Column("tipo_venta", sa.Text(), nullable=False),
            sa.Column("energia_kwh", sa.Numeric(14, 3), nullable=False),
            sa.Column("tarifa_aplicada_kwh", sa.Numeric(12, 6), nullable=False),
            sa.Column("valor_bruto_cop", sa.Numeric(18, 2), nullable=False),
            sa.Column("referencia_factura_xm", sa.String(100), nullable=True),
            sa.Column("fecha_factura_xm", sa.Date(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
