"""Eliminar servicio_operacion y servicio_representacion (0 filas, sin uso real)

Auditoria de Proyectos 2026-08-27. Dos tablas de diseño temprano, nunca
provisionadas via Alembic (Base.metadata.create_all), 0 filas en produccion
las dos:

- servicio_operacion: sin schema, sin endpoint de lectura ni escritura, en
  ningun lado -- solo se referenciaba en el guard de borrado, la fusion de
  duplicados, y una rama de _run_srv_operacion_sync() que siempre comparaba
  contra 0 filas (no-op permanente).
- servicio_representacion: si tenia un schema de solo lectura embebido en
  ProyectoOut y una vista real (ContratosListView.vue, 3 columnas +
  buscador), pero sin NINGUN endpoint de escritura -- las columnas siempre
  mostraban "-", para siempre, porque no hay forma de cargar el dato.

El reemplazo real y vigente de ambos conceptos es la tabla generica
ContratoServicio (servicio_aplica IN ('operacion','representacion',...)),
activamente usada. modalidad_venta/nombre_comercializador/codigo_despacho_xm
(especificos del mercado XM) no tienen equivalente ahi y se pierden --
0% de adopcion nunca en ninguna fila, asi que no hay dato real que perder.

Revision ID: 118
Revises: 117
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import tabla_existe

revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for tabla in ("servicio_operacion", "servicio_representacion"):
        if tabla_existe(bind, tabla):
            op.execute(f"DROP TABLE {tabla}")


def downgrade():
    # 0 filas en las dos, siempre: no hay nada que valga la pena recrear.
    pass
