"""FK con ON DELETE CASCADE en alarma_estado.proyecto_id (y verificación en generacion_diaria).

`alarma_estado` nunca tuvo FK: se creó (y sigue creándose) solo desde el DDL de
arranque de `app/main.py`, con `proyecto_id BIGINT NOT NULL` a secas. Sin FK, al
borrar un proyecto sus filas quedaban huérfanas y el anti-spam de alarmas podía
reusarlas si un proyecto nuevo reciclaba el id.

El `CREATE TABLE IF NOT EXISTS` de main.py ya lleva el FK, pero es no-op sobre
tablas existentes: esta migración es la que arregla las BD ya desplegadas.

`generacion_diaria` ya nació con ON DELETE CASCADE (migración 003a y el modelo
ORM), así que aquí solo se verifica; en la práctica es no-op. A diferencia de
alarma_estado, sus filas son datos reales de generación: si alguna BD tuviera
huérfanas, se aborta con un error en vez de borrarlas en silencio.

Revision ID: 053
Revises: 047
Create Date: 2026-07-13
"""
from alembic import op

revision = "053"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # alarma_estado: estado anti-spam efímero (se reconstruye en el siguiente ciclo de
    # alarmas), así que las huérfanas que impedirían crear el FK se pueden borrar.
    #
    # Nota plpgsql: se usan variables explícitas en vez de FOUND porque cualquier
    # SELECT/DELETE posterior lo reescribe.  'c' = ON DELETE CASCADE (confdeltype).
    op.execute(
        """
        DO $$
        DECLARE
            fk_nombre text;
            fk_accion "char";
            huerfanas bigint;
        BEGIN
            -- BD nueva: la tabla todavía no existe. start.sh corre `alembic upgrade
            -- head` ANTES de levantar la app, y es el DDL de arranque de main.py el
            -- que la crea -- ya con el FK. Nada que arreglar aquí.
            IF to_regclass('public.alarma_estado') IS NULL THEN
                RAISE NOTICE 'alarma_estado aún no existe; el DDL de arranque la creará con el FK';
                RETURN;
            END IF;

            SELECT c.conname, c.confdeltype
              INTO fk_nombre, fk_accion
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.conrelid = 'public.alarma_estado'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'proyecto_id'
             LIMIT 1;

            IF fk_accion = 'c' THEN
                RETURN;  -- ya está en CASCADE
            END IF;

            -- Existe pero con otra acción de borrado (NO ACTION, SET NULL...).
            IF fk_nombre IS NOT NULL THEN
                EXECUTE format('ALTER TABLE alarma_estado DROP CONSTRAINT %I', fk_nombre);
            END IF;

            DELETE FROM alarma_estado a
             WHERE NOT EXISTS (SELECT 1 FROM proyectos p WHERE p.id = a.proyecto_id);
            GET DIAGNOSTICS huerfanas = ROW_COUNT;
            RAISE NOTICE 'alarma_estado: % filas huérfanas borradas', huerfanas;

            -- Mismo nombre que le pondría Postgres al FK inline de main.py, para que
            -- una BD nueva y una migrada converjan al mismo esquema.
            ALTER TABLE alarma_estado
                ADD CONSTRAINT alarma_estado_proyecto_id_fkey
                FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE;
        END $$;
        """
    )

    # generacion_diaria: ya debería estar en CASCADE desde 003a. Se verifica por si
    # alguna BD se construyó por otro camino; nunca se borran filas (son datos reales).
    op.execute(
        """
        DO $$
        DECLARE
            fk_nombre text;
            fk_accion "char";
            huerfanas bigint;
        BEGIN
            IF to_regclass('public.generacion_diaria') IS NULL THEN
                RETURN;
            END IF;

            SELECT c.conname, c.confdeltype
              INTO fk_nombre, fk_accion
              FROM pg_constraint c
              JOIN pg_attribute a
                ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
             WHERE c.conrelid = 'public.generacion_diaria'::regclass
               AND c.contype  = 'f'
               AND a.attname  = 'proyecto_id'
             LIMIT 1;

            IF fk_accion = 'c' THEN
                RETURN;  -- caso normal: no-op
            END IF;

            SELECT count(*)
              INTO huerfanas
              FROM generacion_diaria g
             WHERE NOT EXISTS (SELECT 1 FROM proyectos p WHERE p.id = g.proyecto_id);

            IF huerfanas > 0 THEN
                RAISE EXCEPTION
                    'generacion_diaria tiene % filas con proyecto_id inexistente; son '
                    'datos de generación reales, revísalas a mano antes de crear el FK',
                    huerfanas;
            END IF;

            IF fk_nombre IS NOT NULL THEN
                EXECUTE format('ALTER TABLE generacion_diaria DROP CONSTRAINT %I', fk_nombre);
            END IF;

            ALTER TABLE generacion_diaria
                ADD CONSTRAINT generacion_diaria_proyecto_id_fkey
                FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE;
        END $$;
        """
    )


def downgrade() -> None:
    # Inverso de lo que efectivamente cambió: alarma_estado vuelve a quedarse sin FK.
    # generacion_diaria no se toca: su CASCADE viene de 003a, no de esta migración.
    op.execute(
        "ALTER TABLE IF EXISTS alarma_estado "
        "DROP CONSTRAINT IF EXISTS alarma_estado_proyecto_id_fkey"
    )
