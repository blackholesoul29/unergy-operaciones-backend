"""Fusionar proyecto_inicio_operacion en proyecto_informe_om

Auditoria de "Informe de Puesta en Marcha" 2026-08-31: proyecto_informe_om
tiene 0 filas en produccion (nadie ha guardado nunca un informe) en parte
porque depende de datos (fechas, checklist, pendientes) que solo vivian en
proyecto_inicio_operacion -- tabla que perdio su unico editor el 2026-08-21
y desde entonces no tiene ningun endpoint que la escriba (quedo con 2 filas
de prototipo, no historia real). Un proyecto nuevo no tenia forma de
completar esos datos.

Se fusiona todo en proyecto_informe_om (la tabla con el flujo vivo, el unico
PUT real) y se retira proyecto_inicio_operacion por completo. El checklist
tecnico se estructura en 4 columnas tipadas (antes era un JSONB `checklist`
sin ningun esquema en BD) cubriendo solo las 4 categorias que ya se
resumian en un semaforo -- el resto del catalogo viejo (CCTV, cableado
MT/BT, transformadores, tableros, shelter, obras civiles, paneles,
trackers, checklist detallado por inversor) no se revive, nunca tuvo lector
real (ver docstring de ProyectoInformeOM). Esas 4 categorias SI se mapean
desde el checklist viejo (`_mapear_checklist_viejo()`) para no perder el
poco contenido real que hubiera -- ver "Fix 2026-09-01" mas abajo.

Se agrega ademas un campo `estado` propio (borrador/en_revision/aprobado)
que reemplaza el envio a InformeGuardado/app/api/v1/informes.py (sistema
generico compartido con Mensuales/Portafolio/Ranking, revisor hardcodeado
por email, desconectado de esta ficha).

Fix 2026-09-01 (bloqueo un deploy real, 3 intentos fallidos): la version
original de esta migracion tenia un guard `if any(checklist.values()):
raise RuntimeError(...)` para no perder contenido real del checklist viejo
sin que alguien lo revisara a mano -- pero `any()` daba True con cualquier
sub-diccionario NO VACIO como {"estado": None, "nota": ""} (la forma por
defecto de cada item del checklist, presente SIEMPRE, con o sin datos
reales cargados). En produccion eso disparaba el guard para los 2 unicos
proyectos de la tabla. Revisando a mano resulto que SI habia un par de
valores reales (`estacion_meteo.temperatura_ambiente.estado='pendiente'` en
un proyecto, `cctv='rechazado'` en el otro) -- el primero es de una
categoria que SI se conserva (antes se hubiera perdido igual, el guard
original no la mapeaba a ningun lado); el segundo es de una categoria
explicitamente descartada por decision de la usuaria. Se corrige mapeando
las 4 categorias conservadas en vez de descartar el checklist entero, y se
cambia el guard bloqueante por un aviso informativo (print) solo para
contenido en categorias descartadas -- ya no hay forma de perder algo que
se haya decidido conservar.

Revision ID: 133
Revises: 132
Create Date: 2026-08-31
"""
import json

from alembic import op
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from alembic_idempotencia import agregar_columna_si_falta
import sqlalchemy as sa

revision = "133"
down_revision = "132"
branch_labels = None
depends_on = None


def _tiene_contenido_real(valor) -> bool:
    """True si `valor` trae algun valor hoja genuinamente cargado -- baja
    recursivo por dict/list, así un sub-diccionario placeholder no vacio
    (ej. {"estado": None, "nota": ""}, la forma por defecto de cada item del
    checklist viejo) no cuenta como "contenido real" solo por no estar
    vacio en su nivel superior."""
    if isinstance(valor, dict):
        return any(_tiene_contenido_real(v) for v in valor.values())
    if isinstance(valor, list):
        return any(_tiene_contenido_real(v) for v in valor)
    if isinstance(valor, str):
        return bool(valor.strip())
    return bool(valor)  # None, 0, False -> False; numeros/booleanos reales -> su valor


# Categorias del checklist viejo que NO pasan a las 4 columnas nuevas
# (decision de la usuaria 2026-08-31: solo se conservan Fusion Solar,
# Frontera, Estacion meteo, Reconectador -- el resto nunca tuvo lector real).
_CATEGORIAS_DESCARTADAS = {
    "cctv", "cable_solar", "cableado_mt_bt", "transformadores", "tableros",
    "shelter_skid", "obras_civiles", "doc_om", "paneles", "tracker", "inversores",
}


def _mapear_item(old: dict | None) -> dict:
    old = old or {}
    return {"estado": old.get("estado"), "nota": old.get("nota") or ""}


def _mapear_item_con_evidencia(old: dict | None) -> dict:
    old = old or {}
    return {"estado": old.get("estado"), "nota": old.get("nota") or "", "evidencia": old.get("evidencia") or []}


def _mapear_checklist_viejo(checklist: dict | None) -> dict:
    """Traduce las 4 categorias que SI se conservan del checklist viejo (JSONB
    sin esquema de proyecto_inicio_operacion.checklist) a la forma de las 4
    columnas checklist_* nuevas -- mismos nombres de campo que ya usaba
    InicioOperacionView.vue (borrado 2026-08-21), el mapeo es directo, no una
    reinterpretacion."""
    checklist = checklist or {}
    monitoreo = checklist.get("monitoreo") or {}
    fusion_solar_old = monitoreo.get("fusion_solar") or {}
    frontera = checklist.get("frontera") or {}
    meteo = checklist.get("estacion_meteo") or {}
    reconectador = checklist.get("reconectador") or {}

    return {
        "fusion_solar": {
            "starlink": _mapear_item_con_evidencia(monitoreo.get("starlink")),
            "datos_coherentes": _mapear_item(fusion_solar_old.get("datos_coherentes")),
            "evidencia": fusion_solar_old.get("evidencia") or [],
            "nota": fusion_solar_old.get("nota") or "",
            "inversores": [],
        },
        "frontera": {
            "principal": _mapear_item_con_evidencia(frontera.get("principal")),
            "respaldo": _mapear_item_con_evidencia(frontera.get("respaldo")),
        },
        "estacion_meteo": {
            "instalacion": _mapear_item(meteo.get("instalacion")),
            "en_plataforma": _mapear_item(meteo.get("en_plataforma")),
            "reporta_datos": _mapear_item_con_evidencia(meteo.get("reporta_datos")),
            "poa": _mapear_item(meteo.get("poa")),
            "temperatura_ambiente": _mapear_item(meteo.get("temperatura_ambiente")),
            "velocidad_viento": _mapear_item(meteo.get("velocidad_viento")),
            "direccion_viento": _mapear_item(meteo.get("direccion_viento")),
        },
        "reconectador": {
            "tiene": reconectador.get("tiene"),
            "en_plataforma": _mapear_item(reconectador.get("en_plataforma")),
            "calidad_datos": _mapear_item(reconectador.get("calidad_datos")),
            "evidencia": reconectador.get("evidencia") or [],
            "nota": reconectador.get("nota") or "",
        },
    }


_COLUMNAS_NUEVAS = [
    sa.Column("empresa_contratista", sa.String(255), nullable=True),
    sa.Column("fecha_energizacion", sa.Date, nullable=True),
    sa.Column("fecha_inicio_operacion", sa.Date, nullable=True),
    sa.Column("pendientes", postgresql.JSONB, nullable=False, server_default="[]"),
    sa.Column("checklist_fusion_solar", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_frontera", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_estacion_meteo", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_reconectador", postgresql.JSONB, nullable=False, server_default="{}"),
]


def upgrade():
    bind = op.get_bind()

    for columna in _COLUMNAS_NUEVAS:
        agregar_columna_si_falta(bind, "proyecto_informe_om", columna)

    # create_type=False en la columna: sin eso, un op.add_column futuro que
    # toque esta tabla reemitiria CREATE TYPE al reconstruir la columna y
    # reventaria con DuplicateObject si el tipo ya existe (mismo gotcha que
    # la migracion 131, ver alembic_idempotencia.py).
    estado_enum = postgresql.ENUM(
        "borrador", "en_revision", "aprobado", name="estado_informe_om_enum", create_type=False)
    postgresql.ENUM(
        "borrador", "en_revision", "aprobado", name="estado_informe_om_enum"
    ).create(bind, checkfirst=True)
    agregar_columna_si_falta(
        bind, "proyecto_informe_om",
        sa.Column("estado", estado_enum, nullable=False, server_default="borrador"),
    )

    _migrar_checklist(bind)


def _migrar_checklist(bind) -> None:
    """Backfill de proyecto_inicio_operacion -> proyecto_informe_om (fechas,
    empresa_contratista, pendientes, checklist mapeado) + DROP de la tabla
    vieja. Separada de upgrade() -- que ademas hace DDL especifico de
    Postgres (agregar_columna_si_falta/ENUM) -- para poder probar esta parte
    (la que tuvo el bug real, ver docstring del modulo) contra SQLite en
    tests/test_migracion_informe_om.py -- por eso usa sqlalchemy.inspect() en
    vez de tabla_existe() (information_schema/to_regclass, especifico de
    Postgres, ver mismo gotcha resuelto en la migracion 137)."""
    if "proyecto_inicio_operacion" not in inspect(bind).get_table_names():
        return

    filas = bind.execute(text(
        "SELECT proyecto_id, empresa_contratista, fecha_energizacion, "
        "fecha_inicio_operacion, pendientes, checklist FROM proyecto_inicio_operacion"
    )).mappings().all()

    for fila in filas:
        checklist_viejo = fila["checklist"] or {}
        if isinstance(checklist_viejo, str):
            checklist_viejo = json.loads(checklist_viejo) if checklist_viejo else {}
        pendientes = fila["pendientes"]
        if isinstance(pendientes, str):
            pendientes = json.loads(pendientes) if pendientes else []
        descartado = {k: v for k, v in checklist_viejo.items() if k in _CATEGORIAS_DESCARTADAS}
        if _tiene_contenido_real(descartado):
            claves = sorted(k for k, v in descartado.items() if _tiene_contenido_real(v))
            print(
                f"[migracion 133] proyecto_id={fila['proyecto_id']}: contenido en categorias "
                f"del checklist viejo que ya no se conservan ({', '.join(claves)}) -- se descarta "
                f"a proposito, decision 2026-08-31."
            )

        mapeado = _mapear_checklist_viejo(checklist_viejo)
        if not any((
            fila["empresa_contratista"], fila["fecha_energizacion"], fila["fecha_inicio_operacion"],
            pendientes, _tiene_contenido_real(mapeado),
        )):
            continue

        bind.execute(text("""
            INSERT INTO proyecto_informe_om (proyecto_id, empresa_contratista,
                fecha_energizacion, fecha_inicio_operacion, pendientes,
                checklist_fusion_solar, checklist_frontera, checklist_estacion_meteo, checklist_reconectador)
            VALUES (:proyecto_id, :empresa_contratista, :fecha_energizacion,
                :fecha_inicio_operacion, :pendientes,
                :checklist_fusion_solar, :checklist_frontera,
                :checklist_estacion_meteo, :checklist_reconectador)
            ON CONFLICT (proyecto_id) DO UPDATE SET
                empresa_contratista = COALESCE(proyecto_informe_om.empresa_contratista, EXCLUDED.empresa_contratista),
                fecha_energizacion = COALESCE(proyecto_informe_om.fecha_energizacion, EXCLUDED.fecha_energizacion),
                fecha_inicio_operacion = COALESCE(proyecto_informe_om.fecha_inicio_operacion, EXCLUDED.fecha_inicio_operacion),
                pendientes = CASE WHEN proyecto_informe_om.pendientes = '[]'
                                   THEN EXCLUDED.pendientes ELSE proyecto_informe_om.pendientes END,
                checklist_fusion_solar = CASE WHEN proyecto_informe_om.checklist_fusion_solar = '{}'
                                   THEN EXCLUDED.checklist_fusion_solar ELSE proyecto_informe_om.checklist_fusion_solar END,
                checklist_frontera = CASE WHEN proyecto_informe_om.checklist_frontera = '{}'
                                   THEN EXCLUDED.checklist_frontera ELSE proyecto_informe_om.checklist_frontera END,
                checklist_estacion_meteo = CASE WHEN proyecto_informe_om.checklist_estacion_meteo = '{}'
                                   THEN EXCLUDED.checklist_estacion_meteo ELSE proyecto_informe_om.checklist_estacion_meteo END,
                checklist_reconectador = CASE WHEN proyecto_informe_om.checklist_reconectador = '{}'
                                   THEN EXCLUDED.checklist_reconectador ELSE proyecto_informe_om.checklist_reconectador END
        """), {
            "proyecto_id": fila["proyecto_id"],
            "empresa_contratista": fila["empresa_contratista"],
            "fecha_energizacion": fila["fecha_energizacion"],
            "fecha_inicio_operacion": fila["fecha_inicio_operacion"],
            "pendientes": json.dumps(pendientes or []),
            "checklist_fusion_solar": json.dumps(mapeado["fusion_solar"]),
            "checklist_frontera": json.dumps(mapeado["frontera"]),
            "checklist_estacion_meteo": json.dumps(mapeado["estacion_meteo"]),
            "checklist_reconectador": json.dumps(mapeado["reconectador"]),
        })

    bind.execute(text("DROP TABLE proyecto_inicio_operacion"))


def downgrade():
    # Perdida aceptada para las columnas nuevas y para proyecto_inicio_operacion
    # -- mismo criterio que las migraciones 117/130: no hay contenido real que
    # valga la pena reconstruir (2 filas de prototipo, 0 fichas de informe_om).
    op.execute("""
        CREATE TABLE IF NOT EXISTS proyecto_inicio_operacion (
            id                      BIGSERIAL PRIMARY KEY,
            proyecto_id             BIGINT NOT NULL UNIQUE REFERENCES proyectos(id),
            empresa_contratista     VARCHAR(255),
            fecha_energizacion      DATE,
            fecha_inicio_operacion  DATE,
            checklist               JSONB NOT NULL DEFAULT '{}'::jsonb,
            pruebas                 JSONB NOT NULL DEFAULT '{}'::jsonb,
            documentos              JSONB NOT NULL DEFAULT '{}'::jsonb,
            pendientes              JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyecto_inicio_operacion_proyecto_id "
        "ON proyecto_inicio_operacion(proyecto_id)"
    )
    op.execute("ALTER TABLE proyecto_informe_om DROP COLUMN IF EXISTS estado")
    op.execute("DROP TYPE IF EXISTS estado_informe_om_enum")
    for columna in _COLUMNAS_NUEVAS:
        op.execute(f"ALTER TABLE proyecto_informe_om DROP COLUMN IF EXISTS {columna.name}")
