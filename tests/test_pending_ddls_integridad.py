"""_PENDING_DDLS (app/main.py) -- corre en CADA arranque de la app,
independiente de Alembic (ver _run_column_migrations()). Si una columna se
elimina vía una migración Alembic pero su entrada original
"ADD COLUMN IF NOT EXISTS" queda viva en _PENDING_DDLS, el próximo reinicio
la vuelve a crear (vacía) -- ya pasó una vez de verdad (fronteras, migración
097; feedback_pending_ddls_al_eliminar_columnas) y se repitió el 2026-08-26
con fronteras.quoia_meter_id/estado_operacional (ya limpiado).

Estos tests corren el mismo cruce automatizado usado en esa limpieza, para
que una futura eliminación de columna que se olvide de _PENDING_DDLS falle
acá en vez de resucitar en producción semanas después."""
from __future__ import annotations

import glob
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (tabla, columna) que Alembic dropeó en algún momento pero luego una
# migración POSTERIOR la volvió a agregar de verdad -- la entrada de
# _PENDING_DDLS para esa columna es redundante pero no un bug (auditoría
# 2026-08-26, ver alembic/versions/005_ppa_many_projects.py que dropea
# ppa_contratos.tipo_contrato y 009_ppa_tipo_contrato_carpeta.py que la
# vuelve a crear).
RESURRECCIONES_LEGITIMAS = {
    ("ppa_contratos", "tipo_contrato"),
}


def _parse_pending_ddls():
    """[(indice_de_linea, tabla, columna, 'ADD'|'DROP'), ...] en orden real
    de ejecución dentro de _PENDING_DDLS."""
    main_py = (REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    inicio = main_py.index("_PENDING_DDLS = [")
    fin = main_py.index("\n]", inicio)
    lineas = main_py[inicio:fin].split("\n")

    eventos = []
    for i, linea in enumerate(lineas):
        m = re.search(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", linea)
        if m:
            eventos.append((i, m.group(1), m.group(2), "ADD"))
            continue
        m = re.search(r"ALTER TABLE (\w+) DROP COLUMN IF EXISTS (\w+)", linea)
        if m:
            eventos.append((i, m.group(1), m.group(2), "DROP"))
    return eventos


def _tablas_de_bucle(cuerpo_upgrade: str, archivo_completo: str, var: str) -> list[str]:
    """Resuelve `for <var> in <NOMBRE>:` cuando <NOMBRE> es una lista literal
    de strings -- normalmente definida a nivel de MÓDULO, fuera de
    upgrade() (ver alembic/versions/100_reporte_energia_drop_validado_por.py:
    _TABLAS se define antes de def upgrade(), así que hay que buscarla en el
    archivo completo, no solo dentro del cuerpo de upgrade()). Sin esto, un
    `with op.batch_alter_table(tabla)` dentro de ese for es invisible para
    el regex (no hay ningún literal que capturar) y el cruce de abajo no
    detectaría un drop real ahí. Best-effort: si no encuentra el patrón,
    retorna una lista vacía -- no intenta resolver nada más dinámico que eso
    (ej. nombres de tabla armados en runtime desde una query)."""
    m_for = re.search(rf"for\s+{re.escape(var)}\s+in\s+(\w+)\s*:", cuerpo_upgrade)
    if not m_for:
        return []
    lista_nombre = m_for.group(1)
    m_lista = re.search(rf"{re.escape(lista_nombre)}\s*=\s*\[([^\]]*)\]", archivo_completo)
    if not m_lista:
        return []
    return re.findall(r"['\"](\w+)['\"]", m_lista.group(1))


def _parse_alembic_upgrade_drops():
    """{(tabla, columna)} -- todo lo que algún upgrade() de Alembic dropea
    (downgrade() se ignora a propósito: nunca corre en producción)."""
    drops = set()
    for path in sorted(glob.glob(str(REPO_ROOT / "alembic" / "versions" / "*.py"))):
        txt = Path(path).read_text(encoding="utf-8")
        m_up = re.search(r"\ndef upgrade\(\)[^:]*:\n(.*?)(?=\ndef downgrade|\Z)", txt, re.S)
        if not m_up:
            continue
        cuerpo = m_up.group(1)
        for tabla, col in re.findall(r"op\.drop_column\(\s*['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\s*\)", cuerpo):
            drops.add((tabla, col))
        for bm in re.finditer(
            r"with op\.batch_alter_table\(\s*(['\"]?)(\w+)\1[^)]*\)\s*as\s*batch_op\s*:\n"
            r"(.*?)(?=\n    with op\.batch_alter_table|\n\ndef |\Z)",
            cuerpo, re.S,
        ):
            quoted, nombre_tabla, cuerpo_batch = bm.group(1), bm.group(2), bm.group(3)
            tablas = [nombre_tabla] if quoted else _tablas_de_bucle(cuerpo, txt, nombre_tabla)
            cols = re.findall(r"batch_op\.drop_column\(\s*['\"](\w+)['\"]\s*\)", cuerpo_batch)
            for tabla in tablas:
                for col in cols:
                    drops.add((tabla, col))
    return drops


def test_ninguna_columna_dropeada_por_alembic_sigue_viva_en_pending_ddls():
    eventos = _parse_pending_ddls()
    adds_vivos = {(tabla, col) for _, tabla, col, accion in eventos if accion == "ADD"}
    dropeadas_por_alembic = _parse_alembic_upgrade_drops()

    resurrecciones = (adds_vivos & dropeadas_por_alembic) - RESURRECCIONES_LEGITIMAS

    assert not resurrecciones, (
        "Estas columnas fueron eliminadas por una migración Alembic (upgrade()) "
        "pero _PENDING_DDLS todavía tiene un 'ADD COLUMN IF NOT EXISTS' vivo -- "
        "el próximo arranque de la app las va a resucitar vacías. Borrá la "
        "entrada de _PENDING_DDLS, o si la columna sí debería seguir existiendo "
        "(porque una migración posterior la re-creó a propósito), agregá el par "
        f"a RESURRECCIONES_LEGITIMAS en este archivo: {sorted(resurrecciones)}"
    )


def test_pending_ddls_add_no_queda_despues_de_su_propio_drop_interno():
    """Si una misma (tabla, columna) tiene ADD y DROP DENTRO de _PENDING_DDLS,
    el ADD no puede ser el ÚLTIMO evento de la lista -- si lo es, la columna
    persiste pese a que en algún punto se quiso borrar (bug real). El caso
    contrario (DROP último) es válido -- ya se limpia solo, aunque conviene
    borrar el par entero una vez confirmado en producción."""
    eventos = _parse_pending_ddls()
    from collections import defaultdict
    por_columna = defaultdict(list)
    for idx, tabla, col, accion in eventos:
        por_columna[(tabla, col)].append((idx, accion))

    columnas_add_despues_de_drop = [
        (tabla, col, lst) for (tabla, col), lst in por_columna.items()
        if len(lst) > 1 and sorted(lst)[-1][1] == "ADD"
    ]

    assert not columnas_add_despues_de_drop, (
        f"Estas columnas tienen un DROP seguido de un ADD más abajo en "
        f"_PENDING_DDLS -- la columna termina persistiendo pese al DROP: "
        f"{columnas_add_despues_de_drop}"
    )


def test_pending_ddls_sin_add_duplicado_exacto():
    """Dos entradas ADD COLUMN IF NOT EXISTS idénticas (misma tabla+columna)
    son inofensivas (idempotentes) pero indican una migración que se agregó
    sin revisar si ya existía -- limpiar para no seguir arrastrando ruido."""
    eventos = _parse_pending_ddls()
    from collections import Counter
    adds = [(tabla, col) for _, tabla, col, accion in eventos if accion == "ADD"]
    duplicados = {par: n for par, n in Counter(adds).items() if n > 1}

    assert not duplicados, f"ADD COLUMN duplicados en _PENDING_DDLS: {duplicados}"
