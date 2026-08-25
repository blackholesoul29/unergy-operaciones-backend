"""fronteras: elimina 16 columnas regulatorias sin consumidor real

Auditoria de calidad de datos de Fronteras (2026-08-25), continuacion de
las migraciones 087-095/096. Los 15 campos siguientes solo se mostraban
como texto de solo lectura en FronteraDetailView.vue (InfoField, sin
forma de edicion en el frontend) y no tienen ningun consumidor real en
el backend fuera del propio modelo -- confirmado con grep exhaustivo en
app/ (backend) y src/ (frontend). A diferencia de los campos eliminados
en 087-095, ninguno tiene equivalente en Proyecto, asi que se eliminan
sin reemplazo (no aplica el patron proyecto_* de FronteraOut):

- representante_anterior, nombre_recurso_generacion,
  clasificacion_recurso: texto libre, 94/145 poblados, sin consumidor.
- factor_perdidas, factor_ajuste, factor_acordado, factor_psf,
  factor_perdidas_frontera_principal: factores numericos, 94/145
  poblados. factor_perdidas y es_agrupadora si eran claves en el dict
  de comercial.py (_fronteras_planta, GET /oportunidad/{id}) -- Sara
  confirmo que no tienen consumidor externo y se pueden quitar del
  dict directamente (sin repuntar a Proyecto, a diferencia de
  capacidad_efectiva_mw/municipio/departamento).
- es_agrupadora, es_principal_embebido: booleanos, 145/145 en False
  siempre -- nunca tuvieron un valor real distinto del default.
- codigo_ciiu, clasificacion_industrial_general,
  clasificacion_industrial_especifica, codigo_sic_frontera_generacion,
  codigo_sic_frontera_usuario: codigos de clasificacion, 92-94/145
  poblados, sin consumidor.

Se suma un caso distinto encontrado en la misma revision:
`potencia_maxima_declarada` (94/145 poblados) SI tiene equivalente en
Proyecto -- coincide 1:1 (0 discrepancias en las 94 filas pobladas) con
`Proyecto.potencia_instalada_kwp` convertido a MW, mismo patron que
`capacidad_efectiva_mw`/`capacidad_transporte_mw` (migracion 093). Se
elimina sin agregar un nuevo `proyecto_*` a FronteraOut porque ya existe
`proyecto_potencia_instalada_mw` (agregado en esa misma migracion) y se
muestra en la misma pestana del frontend -- la fila propia de Frontera
era una duplicada exacta, no una fuente de dato distinta.

Se eliminan tambien los 5 CHECK constraints asociados (factor_perdidas/
factor_psf/factor_acordado/factor_ajuste/factor_perdidas_frontera_principal
de la migracion 084, mas potencia_maxima_declarada de la migracion original),
y sus 7 entradas en _PENDING_DDLS (app/main.py) que habrian vuelto a crear
las columnas vacias en cada reinicio del backend -- ver memoria
feedback_pending_ddls_al_eliminar_columnas.

Aparte de Frontera, se elimina tambien `fronteras_quoia_ignoradas.motivo`:
0/5 filas pobladas, el endpoint que lo escribe (POST
/quoia/pendientes/{frt_code}/ignorar) siempre lo recibe en null porque
FronterasView.vue llama `api.post(..., {})` -- nunca hubo un input en el
frontend para cargarlo -- y nadie lo lee (solo se consulta frt_code para
el set de ignorados). Esta tabla no tiene entradas en _PENDING_DDLS (la
crea una migracion propia), asi que no aplica ese riesgo aqui.

Barrido de formato de los 40 campos que quedan en Frontera (pedido
explicito de Sara antes de aplicar esta migracion), 4 hallazgos reales:

- `codigo_frontera`: 100 filas 'Frt...' vs 45 'frt...'. Se normaliza a
  minusculas -- coincide con la convencion de Quoia (el propio frt_code
  siempre viene en minusculas de su API) y con el indice unico existente
  (`ix_fronteras_codigo_frontera_unico`, ya es sobre `lower(codigo_frontera)`
  desde la migracion 077), asi que no hay riesgo de colision nueva.
- `modelo_med_ppal`/`modelo_med_resp`: 'A1830RALN s200' (5 filas) vs
  'A1830RALN S200' (el resto) -- se normaliza a mayusculas.
- `marca_med_resp`: 'Elster'/'Iskra' (43 filas) vs 'ELSTER'/'ISKRA' (el
  resto, y el 100% de marca_med_ppal) -- se normaliza a mayusculas.
- `codigo_sic_submercado_exportador`: 29 filas de consumo
  (consumo_auxiliar/consumo_propio) tienen literalmente el string
  '2026-03-01 00:00:00' en vez de un codigo SIC de 4 caracteres o NULL --
  dato corrupto (una fecha en un campo de codigo), no un codigo real. Sin
  forma de recuperar el valor correcto, se pasan a NULL.

Idempotente (columnas y constraints se verifican antes de tocarlas) por
el mismo motivo que 085/086/094: alembic upgrade head no siempre corre
limpio en el deploy de Railway. El backfill de formato es naturalmente
idempotente (los UPDATE con WHERE no vuelven a tocar filas ya corregidas).

Revision ID: 097
Revises: 096
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None

_COLUMNAS = [
    ("representante_anterior", sa.String(255)),
    ("factor_perdidas", sa.Numeric(10, 6)),
    ("factor_ajuste", sa.Numeric(10, 6)),
    ("factor_acordado", sa.Numeric(10, 6)),
    ("factor_psf", sa.Numeric(10, 6)),
    ("nombre_recurso_generacion", sa.String(255)),
    ("clasificacion_recurso", sa.String(100)),
    ("es_agrupadora", sa.Boolean()),
    ("es_principal_embebido", sa.Boolean()),
    ("factor_perdidas_frontera_principal", sa.Numeric(10, 6)),
    ("codigo_ciiu", sa.String(20)),
    ("clasificacion_industrial_general", sa.String(255)),
    ("clasificacion_industrial_especifica", sa.String(255)),
    ("codigo_sic_frontera_generacion", sa.String(50)),
    ("codigo_sic_frontera_usuario", sa.String(50)),
    ("potencia_maxima_declarada", sa.Numeric(10, 4)),
]

_CHECK_CONSTRAINTS = [
    "ck_fronteras_factor_perdidas_rango",
    "ck_fronteras_factor_psf_no_negativo",
    "ck_fronteras_factor_acordado_no_negativo",
    "ck_fronteras_factor_ajuste_no_negativo",
    "ck_fronteras_factor_perdidas_frontera_principal_no_negativo",
    "ck_fronteras_potencia_maxima_declarada_no_negativa",
]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing_checks = {c["name"] for c in inspector.get_check_constraints("fronteras")}
    for name in _CHECK_CONSTRAINTS:
        if name in existing_checks:
            op.drop_constraint(name, "fronteras", type_="check")

    existing_columns = {c["name"] for c in inspector.get_columns("fronteras")}
    for name, _ in _COLUMNAS:
        if name in existing_columns:
            op.drop_column("fronteras", name)

    existing_ignoradas = {c["name"] for c in inspector.get_columns("fronteras_quoia_ignoradas")}
    if "motivo" in existing_ignoradas:
        op.drop_column("fronteras_quoia_ignoradas", "motivo")

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE fronteras SET codigo_frontera = lower(codigo_frontera) "
        "WHERE codigo_frontera IS NOT NULL AND codigo_frontera != lower(codigo_frontera)"
    ))
    conn.execute(sa.text(
        "UPDATE fronteras SET modelo_med_ppal = upper(modelo_med_ppal) "
        "WHERE modelo_med_ppal IS NOT NULL AND modelo_med_ppal != upper(modelo_med_ppal)"
    ))
    conn.execute(sa.text(
        "UPDATE fronteras SET modelo_med_resp = upper(modelo_med_resp) "
        "WHERE modelo_med_resp IS NOT NULL AND modelo_med_resp != upper(modelo_med_resp)"
    ))
    conn.execute(sa.text(
        "UPDATE fronteras SET marca_med_resp = upper(marca_med_resp) "
        "WHERE marca_med_resp IS NOT NULL AND marca_med_resp != upper(marca_med_resp)"
    ))
    conn.execute(sa.text(
        "UPDATE fronteras SET codigo_sic_submercado_exportador = NULL "
        "WHERE codigo_sic_submercado_exportador = '2026-03-01 00:00:00'"
    ))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing_columns = {c["name"] for c in inspector.get_columns("fronteras")}
    for name, tipo in _COLUMNAS:
        if name not in existing_columns:
            nullable = name not in ("es_agrupadora", "es_principal_embebido")
            kwargs = {} if nullable else {"server_default": sa.false()}
            op.add_column("fronteras", sa.Column(name, tipo, nullable=nullable, **kwargs))

    existing_checks = {c["name"] for c in inspector.get_check_constraints("fronteras")}
    _CONDICIONES = {
        "ck_fronteras_factor_perdidas_rango": "factor_perdidas IS NULL OR (factor_perdidas > 0 AND factor_perdidas <= 2)",
        "ck_fronteras_factor_psf_no_negativo": "factor_psf IS NULL OR factor_psf >= 0",
        "ck_fronteras_factor_acordado_no_negativo": "factor_acordado IS NULL OR factor_acordado >= 0",
        "ck_fronteras_factor_ajuste_no_negativo": "factor_ajuste IS NULL OR factor_ajuste >= 0",
        "ck_fronteras_factor_perdidas_frontera_principal_no_negativo": "factor_perdidas_frontera_principal IS NULL OR factor_perdidas_frontera_principal >= 0",
        "ck_fronteras_potencia_maxima_declarada_no_negativa": "potencia_maxima_declarada IS NULL OR potencia_maxima_declarada >= 0",
    }
    for name, condicion in _CONDICIONES.items():
        if name not in existing_checks:
            op.create_check_constraint(name, "fronteras", condicion)

    existing_ignoradas = {c["name"] for c in inspector.get_columns("fronteras_quoia_ignoradas")}
    if "motivo" not in existing_ignoradas:
        op.add_column("fronteras_quoia_ignoradas", sa.Column("motivo", sa.String(500), nullable=True))
