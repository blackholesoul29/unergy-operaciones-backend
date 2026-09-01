"""Normalizar email_envios: separar destinatarios a tabla hija

Auditoria Reporte CGM 2026-09-01: send_reporte_cgm_email() (y otras 3
funciones de envio -- informe, alarma, falla) insertaban una fila COMPLETA
en email_envios por cada destinatario de correo, aunque el correo real por
SMTP se mandara una sola vez -- un operador con 6 contactos generaba 6
filas "Enviado" identicas en el historial de Reporte CGM. Se normaliza en
dos tablas relacionales (no JSON): email_envios pasa a ser un EVENTO de
envio (una fila por corrida), y los destinatarios reales (to/cc/cco) se
mueven a la tabla hija email_envio_destinatarios.

Verificado en produccion antes de escribir esta migracion: 1065 filas en
email_envios agrupan en 882 eventos reales por (tipo, asunto, minuto de
enviado_at) -- dentro de un mismo loop de envio las inserciones caen en
milisegundos de diferencia, nunca cruzan el minuto (el grupo mas grande
observado, 6 filas de CENS, cayo en un rango de 200ms).

La logica de datos (backfill + colapso) vive en `_migrar_destinatarios()`
en Python puro (no SQL especifico de Postgres) a proposito -- permite
probarla de verdad contra SQLite en tests/test_migracion_email_envios.py,
en vez de solo revisarla a ojo (no hay Postgres local disponible).

El frontend (HistorialEnviosCGM.vue / EnvioInforme) no lee `destinatario`
ni `cc` de email_envios -- solo id/asunto/exitoso/error/enviado_at/
proyectos/proyectos_total, que no cambian. Este es un cambio 100% backend.

Revision ID: 137
Revises: 136
Create Date: 2026-09-01
"""
from alembic import op
from sqlalchemy import inspect, text

from alembic_idempotencia import tabla_existe

revision = "137"
down_revision = "136"
branch_labels = None
depends_on = None


def _minuto(enviado_at) -> str:
    """Trunca a minuto sin importar si el driver devuelve datetime o str
    (SQLite en tests vs. Postgres en produccion) -- ambos formatean el
    prefijo 'YYYY-MM-DD HH:MM' igual en isoformat()/str()."""
    return str(enviado_at)[:16]


def _migrar_destinatarios(bind) -> None:
    """Backfill de email_envio_destinatarios desde destinatario/cc + colapso
    de eventos duplicados. Requiere que email_envio_destinatarios ya exista
    y que email_envios todavia tenga destinatario/cc -- es idempotente
    (no-op) si no.

    Usa sqlalchemy.inspect() en vez de los helpers de alembic_idempotencia
    (information_schema/to_regclass, especificos de Postgres) para que esta
    funcion se pueda probar contra SQLite en
    tests/test_migracion_email_envios.py -- no hay Postgres local disponible.
    """
    insp = inspect(bind)
    if "email_envios" not in insp.get_table_names():
        return
    columnas = {c["name"] for c in insp.get_columns("email_envios")}
    if "destinatario" not in columnas:
        return

    filas = bind.execute(text(
        "SELECT id, destinatario, cc, tipo, asunto, enviado_at, exitoso, error FROM email_envios ORDER BY id"
    )).mappings().all()

    hijos_esperados = 0
    for f in filas:
        if f["destinatario"]:
            bind.execute(text("""
                INSERT INTO email_envio_destinatarios (envio_id, email, tipo_destinatario, exitoso, error)
                VALUES (:envio_id, :email, 'to', :ok, :err)
            """), {"envio_id": f["id"], "email": f["destinatario"], "ok": f["exitoso"], "err": f["error"]})
            hijos_esperados += 1
        for correo in (f["cc"] or "").split(","):
            correo = correo.strip()
            if not correo:
                continue
            bind.execute(text("""
                INSERT INTO email_envio_destinatarios (envio_id, email, tipo_destinatario, exitoso, error)
                VALUES (:envio_id, :email, 'cc', :ok, :err)
            """), {"envio_id": f["id"], "email": correo, "ok": f["exitoso"], "err": f["error"]})
            hijos_esperados += 1

    n_hijos = bind.execute(text("SELECT count(*) FROM email_envio_destinatarios")).scalar()
    if n_hijos != hijos_esperados:
        raise RuntimeError(
            f"Migracion 137: se esperaban {hijos_esperados} filas hijas tras el backfill, "
            f"hay {n_hijos} -- revisar a mano antes de continuar."
        )

    # Colapsar duplicados: mismo (tipo, asunto, minuto) = mismo evento --
    # agrupado en Python (no date_trunc de Postgres) para que la logica sea
    # identica en el test de SQLite y en produccion.
    grupos: dict[tuple, list[int]] = {}
    for f in filas:
        clave = (f["tipo"], f["asunto"], _minuto(f["enviado_at"]))
        grupos.setdefault(clave, []).append(f["id"])

    for ids in grupos.values():
        if len(ids) < 2:
            continue
        ids.sort()
        sobreviviente, *resto = ids
        for id_viejo in resto:
            bind.execute(text(
                "UPDATE email_envio_destinatarios SET envio_id = :sobreviviente WHERE envio_id = :id_viejo"
            ), {"sobreviviente": sobreviviente, "id_viejo": id_viejo})
            bind.execute(text("DELETE FROM email_envios WHERE id = :id_viejo"), {"id_viejo": id_viejo})

    n_hijos_final = bind.execute(text("SELECT count(*) FROM email_envio_destinatarios")).scalar()
    if n_hijos_final != hijos_esperados:
        raise RuntimeError(
            f"Migracion 137: el colapso de duplicados perdio filas hijas "
            f"({hijos_esperados} antes, {n_hijos_final} despues) -- revisar a mano."
        )

    bind.execute(text("ALTER TABLE email_envios DROP COLUMN destinatario"))
    bind.execute(text("ALTER TABLE email_envios DROP COLUMN cc"))


def upgrade():
    bind = op.get_bind()

    if not tabla_existe(bind, "email_envio_destinatarios"):
        op.execute("""
            CREATE TABLE email_envio_destinatarios (
                id                BIGSERIAL PRIMARY KEY,
                envio_id          BIGINT NOT NULL REFERENCES email_envios(id) ON DELETE CASCADE,
                email             VARCHAR(500) NOT NULL,
                tipo_destinatario VARCHAR(10) NOT NULL DEFAULT 'to',
                exitoso           BOOLEAN NOT NULL,
                error             TEXT
            )
        """)
        op.execute(
            "CREATE INDEX ix_email_envio_destinatarios_envio_id "
            "ON email_envio_destinatarios(envio_id)"
        )

    _migrar_destinatarios(bind)


def downgrade():
    bind = op.get_bind()
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS destinatario VARCHAR(500)")
    op.execute("ALTER TABLE email_envios ADD COLUMN IF NOT EXISTS cc TEXT")

    # Mejor esfuerzo: reconstruye un 'destinatario' (el primer 'to') y un
    # 'cc' (el resto, unido por coma) por evento -- un evento colapsado no
    # vuelve a partirse en N filas como antes de esta migracion, pero
    # ningun destinatario real se pierde.
    if tabla_existe(bind, "email_envio_destinatarios"):
        eventos = bind.execute(text("SELECT id FROM email_envios")).all()
        for (envio_id,) in eventos:
            destinatarios = bind.execute(text(
                "SELECT email, tipo_destinatario FROM email_envio_destinatarios "
                "WHERE envio_id = :id ORDER BY id"
            ), {"id": envio_id}).all()
            principal = next((e for e, t in destinatarios if t == "to"), None)
            resto = [e for e, t in destinatarios if e != principal]
            bind.execute(text(
                "UPDATE email_envios SET destinatario = :d, cc = :cc WHERE id = :id"
            ), {"d": principal, "cc": ",".join(resto) or None, "id": envio_id})

    op.execute("DROP TABLE IF EXISTS email_envio_destinatarios")
