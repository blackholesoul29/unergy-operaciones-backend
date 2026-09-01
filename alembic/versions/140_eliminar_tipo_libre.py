"""Eliminar fallas.tipo_libre

Auditoria del dominio Fallas 2026-09-02: `tipo_libre` era un campo derivado
que se recalculaba en cada guardado de una falla estructurada
(`_aplicar_clasificacion`) y se volvia a recalcular en cada arranque del
servidor via un backfill permanente (`_run_fallas_tipo_backfill` /
`backfill_tipos_estructurados`, ambos eliminados el mismo dia) -- un
dry-run real contra produccion mostro 0 correcciones sobre 5.086 fallas
estructuradas, confirmando que ya no hacia falta. El titulo que mostraba
ahora se arma al vuelo desde `clasificacion` (ver
app/services/fallas/titulo.py), sin necesidad de guardar ni sincronizar
nada.

Antes de poder dropear la columna hay que resolver las fallas que
dependian de verdad de su texto libre (sin `categoria_codigo` ni `tipo_id`
que lo reemplace) -- 14 filas reales en produccion, revisadas una por una:

  - 4 (reconexion remota tras desconexion) -> red.desconexion_sin_identificar
  - 1 (disparo de totalizador por sobretension) -> red.alta_tension
  - 2 (pruebas del operador de red en el reconectador) -> red.mantenimiento_red
  - 6 (socavamiento del terreno, sin categoria electrica que le calce) ->
    eventos_adversos.otro (decision de negocio 2026-09-02: no se crea una
    categoria nueva para esto)
  - 1 (falla de prueba QA, la propia descripcion dice "borrar") -> soft-delete

Una fila adicional (FAL-2026-05659) tenia tipo_id legacy real (67) y
tipo_libre='s' -- un error de tipeo de una sola letra, sin contenido que
preservar; no necesita reclasificacion, solo pierde la columna como todas
las demas.

Revision ID: 140
Revises: 139
Create Date: 2026-09-02
"""
import json

from alembic import op
from sqlalchemy import text

from alembic_idempotencia import columna_existe

revision = "140"
down_revision = "139"
branch_labels = None
depends_on = None


# codigo_interno -> (categoria_codigo, subtipo_codigo, subtipo_etiqueta,
#                     categoria_etiqueta, subtipo_detalle, pendiente_reclasificar)
_RECLASIFICAR = {
    "FAL-2026-05599": ("red", "desconexion_sin_identificar", "Desconexión sin identificar", "Red", None, True),
    "FAL-2026-05600": ("red", "desconexion_sin_identificar", "Desconexión sin identificar", "Red", None, True),
    "FAL-2026-05601": ("red", "desconexion_sin_identificar", "Desconexión sin identificar", "Red", None, True),
    "FAL-2026-05628": ("red", "desconexion_sin_identificar", "Desconexión sin identificar", "Red", None, True),
    "FAL-2026-05649": ("red", "alta_tension", "Alta tensión", "Red", None, False),
    "FAL-2026-05651": ("red", "mantenimiento_red", "Mantenimiento de red", "Red",
                        "Pruebas del operador de red (Acovis) en el reconectador", False),
    "FAL-2026-05652": ("red", "mantenimiento_red", "Mantenimiento de red", "Red",
                        "Pruebas del operador de red (Acovis) en el reconectador", False),
    "FAL-2026-05635": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
    "FAL-2026-05636": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
    "FAL-2026-05637": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
    "FAL-2026-05638": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
    "FAL-2026-05642": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
    "FAL-2026-05644": ("eventos_adversos", "otro", "Otro", "Eventos naturales", "Socavamiento del terreno", False),
}

_SOFT_DELETE = ["FAL-2026-05585"]  # "PRUEBA QA app movil (borrar)"


def upgrade() -> None:
    bind = op.get_bind()
    if not columna_existe(bind, "fallas", "tipo_libre"):
        return

    for codigo, (cat_cod, subtipo_cod, subtipo_et, cat_et, detalle, pendiente) in _RECLASIFICAR.items():
        tipo_row = bind.execute(text(
            "SELECT id FROM fallas_cat_tipos WHERE codigo = :c AND activa = TRUE LIMIT 1"
        ), {"c": f"{cat_cod}.{subtipo_cod}"}).first()

        clasif = {"categoria": cat_cod, "categoria_etiqueta": cat_et,
                   "subtipo": subtipo_cod, "subtipo_etiqueta": subtipo_et}
        if detalle:
            clasif["detalle"] = detalle

        bind.execute(text("""
            UPDATE fallas SET
                categoria_codigo = :cat_cod,
                subtipo_codigo = :subtipo_cod,
                subtipo_detalle = :detalle,
                pendiente_reclasificar = :pendiente,
                tipo_id = :tipo_id,
                clasificacion = :clasif
            WHERE codigo_interno = :codigo AND deleted_at IS NULL
        """), {
            "cat_cod": cat_cod, "subtipo_cod": subtipo_cod, "detalle": detalle,
            "pendiente": pendiente, "tipo_id": tipo_row[0] if tipo_row else None,
            "clasif": json.dumps(clasif), "codigo": codigo,
        })

    for codigo in _SOFT_DELETE:
        bind.execute(text(
            "UPDATE fallas SET deleted_at = now() WHERE codigo_interno = :codigo AND deleted_at IS NULL"
        ), {"codigo": codigo})

    # DROP COLUMN se lleva consigo cualquier indice que viviera sobre ella.
    op.drop_column("fallas", "tipo_libre")


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    if columna_existe(bind, "fallas", "tipo_libre"):
        return
    op.add_column("fallas", sa.Column("tipo_libre", sa.String(255), nullable=True))
    # No se revierte la reclasificacion ni el soft-delete -- son datos reales
    # corregidos, no un efecto secundario de la columna.
