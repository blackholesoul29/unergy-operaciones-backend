"""Toda columna nueva del modelo tiene que estar en el DDL que corre al arrancar.

Por que existe esta prueba: `start.sh` ejecuta `alembic upgrade head` dentro de un
`if !`, asi que cuando una migracion falla el arranque CONTINUA y la app queda
pidiendo columnas que la base no tiene. El sintoma no es un error de despliegue
sino un 500 al abrir la pantalla, porque revienta cualquier SELECT sobre esa
tabla.

Ya paso tres veces. `sunfactory_project_id` (migration 031) tiene su propio
comentario en `_PENDING_DDLS` explicandolo, y el 2026-08-25 se cayeron /proyectos
y /ppa por `proyectos.altitud_msnm` y `proyectos.project_id_solarview`, mas cuatro
columnas `xm_*` en cada tabla de reporte_energia.

La regla del repo (CLAUDE.md) es que una columna nueva sobre una tabla que YA
existe se provisiona con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en el DDL que
si corre — `_PENDING_DDLS` de `app/main.py` o `init_db.py` — y no solo con una
migracion de Alembic.

Se vigila `proyectos` y no todas las tablas a proposito: es la que rompe mas
pantallas cuando falla (proyectos, ppa, fallas, liquidaciones y contratos cargan
su relacion), y vigilarlas todas exigiria congelar cientos de columnas originales
sin ganar deteccion real.
"""
import io
import glob
import re
from pathlib import Path

import app.models  # noqa: F401  — registra todos los modelos en el metadata
from app.models.base import Base

RAIZ = Path(__file__).resolve().parent.parent

# Columnas de `proyectos` que ya vivian en produccion antes de que el repo
# empezara a exigir ALTER explicito: las creo `create_all` cuando nacio la tabla,
# asi que no aparecen en ningun DDL y no hay forma de deducirlo leyendo el codigo.
# Congeladas el 2026-08-25.
#
# NO agregues nada aca para silenciar la prueba: si la columna es nueva, lo que
# falta es su ALTER en `_PENDING_DDLS`. Esta lista solo describe el pasado.
COLUMNAS_ORIGINALES_PROYECTOS = {
    # Verificadas una por una con `git log -S <col> -- app/models/proyectos.py`:
    # todas entraron en el commit inicial o antes de que el repo exigiera ALTER.
    'carpeta_drive_codigo',
    'clasificacion_regulatoria',
    'codigo_cnd',
    'created_at',
    'departamento',
    'direccion_vereda',
    'estado',
    'fecha_entrada_operacion',
    'id',
    'latitud',
    'longitud',
    'municipio',
    'nombre_comercial',
    'potencia_con_cen_mw',
    'potencia_instalada_kwp',
    'project_id_solenium',
    'srv_cgm',
    'srv_ppa',
    'srv_promotor',
    'srv_rec',
    'srv_representacion',
    'tipo_conexion',
    'tipo_proyecto',
    'tipo_tecnologia',
    'topic_slug',
    'updated_at',
}

# Las diez que tumbaron produccion el 2026-08-25.
COLUMNAS_DEL_INCIDENTE = [
    ('proyectos', 'altitud_msnm'),
    ('proyectos', 'project_id_solarview'),
    ('reporte_energia_consumo', 'xm_process_id'),
    ('reporte_energia_consumo', 'xm_estado'),
    ('reporte_energia_consumo', 'xm_exitoso'),
    ('reporte_energia_consumo', 'xm_verificado_en'),
    ('reporte_energia_generacion', 'xm_process_id'),
    ('reporte_energia_generacion', 'xm_estado'),
    ('reporte_energia_generacion', 'xm_exitoso'),
    ('reporte_energia_generacion', 'xm_verificado_en'),
    # No es del incidente, pero se agrego despues sobre una tabla que ya existia
    # y le aplica la misma regla: sin ALTER, /contratos-servicio devolveria 500.
    ('contratos_servicio', 'inversionista_id'),
]


def _ddl_que_corre() -> str:
    """Solo el DDL que se ejecuta de verdad al arrancar.

    Alembic queda fuera a proposito: es justo lo que puede fallar sin detener el
    despliegue, y darlo por bueno seria no probar nada.
    """
    partes = []
    for rel in ('app/main.py', 'app/core/init_db.py', 'init_db.py'):
        for f in glob.glob(str(RAIZ / rel)):
            partes.append(io.open(f, encoding='utf-8').read())
    return '\n'.join(partes)


def _provisionada(tabla: str, columna: str, ddl: str) -> bool:
    """Hay un ALTER sobre ESA tabla que crea ESA columna.

    Se exige la tabla y no solo el nombre de la columna: dos tablas distintas
    pueden tener una columna homonima, y darla por cubierta porque otra la nombra
    es justo el falso negativo que deja pasar el 500. Paso de verdad —
    `proyectos.tipo_tecnologia` parecia cubierta porque `fronteras` tenia una
    columna con el mismo nombre, hasta que la de fronteras se elimino.
    """
    return bool(re.search(
        rf'ALTER TABLE {re.escape(tabla)} ADD COLUMN IF NOT EXISTS {re.escape(columna)}\b',
        ddl))


def test_columnas_de_proyectos_provisionadas():
    ddl = _ddl_que_corre()
    tabla = Base.metadata.tables['proyectos']

    sin_ddl = {c.name for c in tabla.columns
               if not _provisionada('proyectos', c.name, ddl)}
    nuevas = sorted(sin_ddl - COLUMNAS_ORIGINALES_PROYECTOS)

    assert not nuevas, (
        f'Estas columnas de `proyectos` estan en el modelo pero ningun DDL que se '
        f'ejecute al arrancar las crea: {nuevas}.\n'
        f'Agrega "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS <col> <tipo>" a '
        f'_PENDING_DDLS en app/main.py. Una migracion de Alembic NO basta: '
        f'start.sh la corre dentro de un `if !`, el arranque sigue aunque falle, '
        f'y la app queda devolviendo 500 en cada consulta a proyectos.'
    )


def test_columnas_del_incidente_2026_08_25():
    """Las diez concretas, con su ALTER, no solo mencionadas en un comentario."""
    ddl = _ddl_que_corre()
    faltan = [f'{t}.{c}' for t, c in COLUMNAS_DEL_INCIDENTE
              if not re.search(
                  rf'ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c}\b', ddl)]
    assert not faltan, f'sin ALTER en el DDL que corre: {faltan}'


def test_el_arranque_no_se_detiene_si_alembic_falla():
    """Fija el porque de esta prueba: mientras `start.sh` siga tolerando el fallo
    de Alembic, el DDL de `_PENDING_DDLS` es la unica garantia real.

    Si algun dia el arranque pasa a abortar cuando la migracion falla, esta
    prueba falla y toca revisar si el resto del archivo sigue teniendo sentido.
    """
    start = io.open(RAIZ / 'start.sh', encoding='utf-8').read()
    assert 'if ! alembic upgrade head' in start, (
        'start.sh cambio: si ahora aborta cuando Alembic falla, revisa si estas '
        'pruebas siguen haciendo falta.'
    )
