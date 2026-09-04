"""Falla si la base no tiene todo lo que declaran los modelos de Django.

Gemelo de `verificar_esquema.py`, que hace lo mismo con los modelos de
SQLAlchemy. Existen los dos porque durante la coexistencia hay dos juegos de
modelos sobre las MISMAS tablas, y el de SQLAlchemy no sabe nada del de Django:
una columna declarada solo en `apps/` pasaba el deploy limpio y reventaba en
runtime con `ProgrammingError: column ... does not exist`. Verificado el
2026-09-04 agregando un campo de prueba a `RetoTrimestre`.

Tiene un segundo uso, y es el importante: **es la prueba que hay que pasar antes
de darle el esquema a Django.** El dia del corte, `makemigrations` va a generar
un `0001_initial` que es la foto contra la que Django comparara TODOS los
cambios futuros. Si esa foto miente en un solo detalle, la segunda migracion
emitira DDL para "corregir" produccion contra algo que nunca fue. Estos modelos
los genero un script desde SQLAlchemy y ya se le encontraron dos clases de
error (los `server_default` perdidos, las claves primarias compuestas), asi que
la fidelidad hay que medirla, no suponerla.

Uso:

    python scripts/verificar_esquema_django.py            # falla si falta algo
    python scripts/verificar_esquema_django.py --extra    # ademas, lo que sobra

Comprueba dos cosas distintas: que exista en la base todo lo que el modelo
declara, y que el modelo declare un `default=` por cada columna NOT NULL que la
base rellena sola (ver `_sin_default` -- Django manda TODAS las columnas en un
INSERT, así que el DEFAULT de la base nunca llega a aplicarse).

`--extra` lista las columnas que la base tiene y el modelo no declara. No es un
error -- Django ignora una columna que no conoce, y con `null=True` o un default
en la base ni siquiera estorba en un INSERT -- pero SI importa el dia del corte:
cada una de esas columnas desaparece del `0001_initial`, y una migracion
posterior podria proponer borrarla.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection  # noqa: E402

# La isla de Django: sus tablas las crea `manage.py migrate`, no Alembic, asi
# que aca no se revisan. Es la misma lista de `tests/test_frontera_esquema.py`.
APPS_DE_LA_ISLA = {"contenttypes", "django_celery_beat"}


def _columnas_de_la_base() -> dict[str, set[str]]:
    """`{tabla: {columna}}` para todo el esquema public, en UNA consulta.

    Una consulta por tabla serian 121 idas a la base para un script que corre en
    el arranque del deploy.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        salida: dict[str, set[str]] = {}
        for tabla, columna in cur.fetchall():
            salida.setdefault(tabla, set()).add(columna)
    return salida


def _columnas_del_modelo(modelo) -> set[str]:
    """Las columnas REALES que el modelo declara.

    `local_fields` y no `fields`: hereda los de las tablas padre en una herencia
    multi-tabla, que no es el caso aca, pero tambien excluye los campos inversos
    y los many-to-many, que no son columnas de esta tabla.
    """
    return {
        campo.column for campo in modelo._meta.local_fields
        if campo.column is not None
    }


def _defaults_de_la_base() -> dict[str, dict[str, str]]:
    """`{tabla: {columna: default}}` de las columnas NOT NULL que la base rellena
    sola."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND is_nullable = 'NO' "
            "AND column_default IS NOT NULL"
        )
        salida: dict[str, dict[str, str]] = {}
        for tabla, columna, defecto in cur.fetchall():
            salida.setdefault(tabla, {})[columna] = defecto
    return salida


def _sin_default(modelo, defaults: dict[str, str]) -> list[str]:
    """Columnas NOT NULL que la base rellena sola pero el modelo no.

    **Django manda TODAS las columnas en un INSERT.** Un `DEFAULT` de la base
    solo se aplica cuando la columna se omite, y Django nunca la omite: manda
    NULL explícito y el INSERT muere contra el NOT NULL. Por eso un default de
    la base tiene que estar ADEMÁS en el modelo.

    No falla con un `Alembic` detrás que lo tape ni en un SELECT: solo la
    primera vez que alguien intenta crear una fila desde Django. Se encontró así
    el 2026-09-04, al portar el job de alertas de PPA — `alertas.trigger_date`
    es `NOT NULL DEFAULT CURRENT_DATE` y el modelo no lo declaraba, junto con 18
    columnas JSONB más.
    """
    problemas = []
    for campo in modelo._meta.local_fields:
        defecto = defaults.get(campo.column)
        if not defecto or "nextval" in defecto:
            continue   # las secuencias las resuelve el AutoField
        if (campo.has_default() or getattr(campo, "auto_now", False)
                or getattr(campo, "auto_now_add", False)):
            continue
        problemas.append(
            f"{modelo._meta.db_table}.{campo.column}: la base la rellena con "
            f"{defecto} y el modelo no declara `default=`"
        )
    return problemas


def revisar() -> tuple[list[str], list[str], int]:
    """`(faltantes, sobrantes, modelos revisados)`."""
    en_db = _columnas_de_la_base()
    defaults = _defaults_de_la_base()
    faltan: list[str] = []
    sobran: list[str] = []
    revisados = 0

    for modelo in apps.get_models():
        if modelo._meta.app_label in APPS_DE_LA_ISLA:
            continue
        revisados += 1
        tabla = modelo._meta.db_table
        if tabla not in en_db:
            faltan.append(f"{tabla}: la tabla no existe")
            continue
        declaradas = _columnas_del_modelo(modelo)
        for columna in sorted(declaradas - en_db[tabla]):
            faltan.append(f"{tabla}.{columna}: la columna no existe")
        faltan.extend(_sin_default(modelo, defaults.get(tabla, {})))
        for columna in sorted(en_db[tabla] - declaradas):
            sobran.append(f"{tabla}.{columna}")

    return faltan, sobran, revisados


def main() -> int:
    mostrar_extra = "--extra" in sys.argv
    faltan, sobran, revisados = revisar()

    if mostrar_extra and sobran:
        print(f"[esquema-django] {len(sobran)} columnas en la base que el modelo "
              "NO declara:")
        for s in sobran:
            print(f"  - {s}")
        print()

    if not faltan:
        print(f"[esquema-django] OK — {revisados} modelos, todas sus columnas "
              "estan en la base")
        return 0

    print("[esquema-django] El modelo y la base no coinciden:")
    for f in faltan:
        print(f"  - {f}")
    print("\nDjango posee el esquema desde el 2026-09-04: una columna que falta es")
    print("una migracion sin generar (`makemigrations`) o sin aplicar (`migrate`).")
    print("Un `default=` que falta no es DDL -- es que el modelo no sabe lo que la")
    print("base ya hace, y Django manda NULL en el INSERT.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
