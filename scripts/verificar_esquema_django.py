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


def revisar() -> tuple[list[str], list[str], int]:
    """`(faltantes, sobrantes, modelos revisados)`."""
    en_db = _columnas_de_la_base()
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

    print("[esquema-django] La base NO tiene lo que el modelo de Django declara:")
    for f in faltan:
        print(f"  - {f}")
    print("\nMientras Alembic sea el dueno del esquema, falta la revision que lo")
    print("provisiona: declarar el campo en `apps/` no crea nada (los modelos son")
    print("`managed = False`, asi que `makemigrations` genera un no-op).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
