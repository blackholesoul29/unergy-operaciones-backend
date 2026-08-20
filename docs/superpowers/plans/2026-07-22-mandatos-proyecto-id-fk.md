# FK `mandatos.proyecto_id` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir una llave foránea real `mandatos.proyecto_id → proyectos.id`, enlazar los históricos por nombre exacto y hacer que los nuevos mandatos nazcan enlazados, conservando el texto `proyecto` como legacy.

**Architecture:** El esquema se provisiona por la vía garantizada del repo (bloque `_PENDING_DDLS` de arranque en `main.py`) más una migración Alembic de paridad; ambos idempotentes (`IF NOT EXISTS`). El backfill corre como paso idempotente en `_deferred_init` (patrón de `_run_arr_link_backfill`), usando una función pura de match exacto. El enlazado al crear reutiliza `find_proyecto_by_name`.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 (Mapped) · Alembic · PostgreSQL · pytest

---

## Archivos afectados

- **Crear:** `app/services/mandato_link.py` — función pura de match exacto + backfill con sesión.
- **Crear:** `alembic/versions/047_mandato_proyecto_id.py` — migración de paridad.
- **Crear:** `tests/test_mandato_link.py` — tests puros del matcher.
- **Modificar:** `app/models/mandatos.py` — columna FK + relación.
- **Modificar:** `app/main.py` — DDL en `_PENDING_DDLS` + registrar backfill en `_deferred_init`.
- **Modificar:** `app/api/v1/mandatos.py` — enlazar `proyecto_id` en `crear` y `upload_zip`.
- **Modificar:** `app/services/mandatos_service.py` — exponer `proyecto_id` en `mandato_to_dict`.
- **Modificar:** `tests/test_mandatos.py` — actualizar helper `_row` + test de `proyecto_id`.

---

### Task 1: Columna FK en el modelo

**Files:**
- Modify: `app/models/mandatos.py:49-53`

- [ ] **Step 1: Añadir la columna y la relación**

En `app/models/mandatos.py`, dentro de `class Mandato`, justo después de la línea `proyecto: Mapped[str | None] = mapped_column(String(255), nullable=True)` (línea 49), insertar:

```python
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

Y al final de la clase (después de la relación `inversionista`, línea 70), añadir la relación unidireccional (nombre distinto del campo texto `proyecto`):

```python
    proyecto_rel: Mapped["Proyecto | None"] = relationship("Proyecto")
```

`BigInteger`, `ForeignKey` y `relationship` ya están importados (líneas 4-8). No se necesita import nuevo.

- [ ] **Step 2: Verificar que el modelo importa sin error**

Run: `python -c "from app.models.mandatos import Mandato; print(Mandato.__table__.c.proyecto_id)"`
Expected: imprime `mandatos.proyecto_id` sin excepción.

- [ ] **Step 3: Commit**

```bash
git add app/models/mandatos.py
git commit -m "feat(mandatos): add proyecto_id FK column to Mandato model"
```

---

### Task 2: DDL idempotente en el arranque (vía garantizada)

**Files:**
- Modify: `app/main.py:1036-1038` (final de la lista `_PENDING_DDLS`)

- [ ] **Step 1: Añadir el ALTER y el índice al final de `_PENDING_DDLS`**

En `app/main.py`, localizar el final de la lista `_PENDING_DDLS`. Reemplazar este bloque:

```python
    # Vínculo estructurado de operador de red también en proyectos (2026-07-10)
    # -- antes solo existía en fronteras, y sin forma de editarlo desde la API.
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS operador_red_id BIGINT REFERENCES operadores_red(id)",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_operador_red_id ON proyectos (operador_red_id)",
]
```

por:

```python
    # Vínculo estructurado de operador de red también en proyectos (2026-07-10)
    # -- antes solo existía en fronteras, y sin forma de editarlo desde la API.
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS operador_red_id BIGINT REFERENCES operadores_red(id)",
    "CREATE INDEX IF NOT EXISTS ix_proyectos_operador_red_id ON proyectos (operador_red_id)",
    # FK mandatos → proyectos (2026-07-22) -- antes 'proyecto' era solo texto.
    "ALTER TABLE mandatos ADD COLUMN IF NOT EXISTS proyecto_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_mandatos_proyecto_id ON mandatos (proyecto_id)",
]
```

- [ ] **Step 2: Verificar sintaxis del módulo**

Run: `python -c "import ast; ast.parse(open('app/main.py', encoding='utf-8').read()); print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat(mandatos): provision proyecto_id column via startup DDL"
```

---

### Task 3: Migración Alembic de paridad

**Files:**
- Create: `alembic/versions/047_mandato_proyecto_id.py`

- [ ] **Step 1: Crear el archivo de migración**

```python
"""FK mandatos.proyecto_id -> proyectos.id.

Provisionada también por el bloque DDL de arranque (main.py); esta migración
existe para paridad/historia y desarrollo local. Idempotente (IF NOT EXISTS).

Revision ID: 047
Revises: 046
Create Date: 2026-07-22
"""
from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mandatos ADD COLUMN IF NOT EXISTS "
        "proyecto_id BIGINT REFERENCES proyectos(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mandatos_proyecto_id ON mandatos (proyecto_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_mandatos_proyecto_id")
    op.execute("ALTER TABLE mandatos DROP COLUMN IF EXISTS proyecto_id")
```

- [ ] **Step 2: Verificar que Alembic reconoce un único head = 047**

Run: `alembic heads`
Expected: una sola línea que incluye `047 (head)`.

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/047_mandato_proyecto_id.py
git commit -m "feat(mandatos): alembic 047 add proyecto_id FK (parity)"
```

---

### Task 4: Función pura de match exacto + backfill (TDD)

**Files:**
- Create: `tests/test_mandato_link.py`
- Create: `app/services/mandato_link.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_mandato_link.py`:

```python
"""Tests de la función pura de emparejamiento exacto de proyecto para mandatos."""
from app.services.mandato_link import emparejar_proyecto_exacto

CANDIDATOS = [
    (10, "Minigranja Solar Baraya"),
    (11, "Minigranja Solar Uruaco"),
    (12, "PSF - Yurbaqua"),
]


def test_match_exacto_devuelve_id():
    assert emparejar_proyecto_exacto("Minigranja Solar Baraya", CANDIDATOS) == 10


def test_match_normaliza_tildes_y_mayusculas():
    assert emparejar_proyecto_exacto("minigranja solar uruacó", CANDIDATOS) == 11


def test_sin_match_devuelve_none():
    assert emparejar_proyecto_exacto("GD 1MVA San Onofre", CANDIDATOS) is None


def test_ambiguo_devuelve_none():
    dup = CANDIDATOS + [(99, "Minigranja Solar Baraya")]
    assert emparejar_proyecto_exacto("Minigranja Solar Baraya", dup) is None


def test_nombre_vacio_devuelve_none():
    assert emparejar_proyecto_exacto("", CANDIDATOS) is None
    assert emparejar_proyecto_exacto(None, CANDIDATOS) is None
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/test_mandato_link.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.mandato_link'`.

- [ ] **Step 3: Implementar el servicio**

Crear `app/services/mandato_link.py`:

```python
"""Enlazado de mandatos con proyectos por nombre exacto normalizado.

- `emparejar_proyecto_exacto`: función PURA (sin BD), testeable.
- `backfill_mandato_proyecto_links`: rellena mandatos.proyecto_id NULL usando la
  función pura contra el catálogo de proyectos. Conservador: solo match exacto;
  ambiguo o sin match => queda NULL (mejor NULL que enlace equivocado).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mandatos import Mandato
from app.models.proyectos import Proyecto
from app.utils.nombre_matching import normalizar


def emparejar_proyecto_exacto(nombre, candidatos) -> int | None:
    """Devuelve el id del proyecto cuyo nombre normalizado coincide EXACTAMENTE
    con `nombre`. None si hay 0 o más de 1 coincidencia.

    :param candidatos: iterable de tuplas (id, nombre_comercial).
    """
    objetivo = normalizar(nombre or "")
    if not objetivo:
        return None
    ids = [cid for cid, cnombre in candidatos if normalizar(cnombre or "") == objetivo]
    return ids[0] if len(ids) == 1 else None


def backfill_mandato_proyecto_links(db: Session) -> dict:
    """Rellena mandatos.proyecto_id NULL por match exacto. Fill-if-null."""
    candidatos = [
        (pid, nombre)
        for pid, nombre in db.execute(
            select(Proyecto.id, Proyecto.nombre_comercial)
        ).all()
    ]
    mandatos = db.execute(
        select(Mandato).where(
            Mandato.proyecto_id.is_(None), Mandato.proyecto.isnot(None)
        )
    ).scalars().all()

    vinculados = 0
    sin_match: list[str] = []
    for m in mandatos:
        pid = emparejar_proyecto_exacto(m.proyecto, candidatos)
        if pid:
            m.proyecto_id = pid
            vinculados += 1
        else:
            sin_match.append(m.proyecto)
    if vinculados:
        db.commit()
    return {"vinculados": vinculados, "sin_match": sin_match}
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `pytest tests/test_mandato_link.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandato_link.py tests/test_mandato_link.py
git commit -m "feat(mandatos): exact-match project linker + backfill service"
```

---

### Task 5: Registrar el backfill en el arranque

**Files:**
- Modify: `app/main.py` (nueva función `_run_mandato_proyecto_backfill` cerca de `_run_arr_link_backfill:2596`; registro en `_deferred_init:2619-2633`)

- [ ] **Step 1: Añadir la función de arranque**

En `app/main.py`, justo después de la función `_run_arr_link_backfill` (termina en la línea `db.close()` ~2610), añadir:

```python
def _run_mandato_proyecto_backfill() -> None:
    """Enlaza mandatos.proyecto_id por nombre exacto (fill-if-null). Idempotente."""
    from sqlalchemy.orm import sessionmaker
    from app.services.mandato_link import backfill_mandato_proyecto_links

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        rep = backfill_mandato_proyecto_links(db)
        if rep["vinculados"]:
            print(f"[mandato_link] {rep['vinculados']} vinculados, "
                  f"{len(rep['sin_match'])} sin match")
    finally:
        db.close()
```

- [ ] **Step 2: Registrar el paso en `_deferred_init`**

En la lista de `_deferred_init` (líneas 2619-2633), reemplazar la línea:

```python
        ("fallas_tipo_backfill", _run_fallas_tipo_backfill),
```

por:

```python
        ("fallas_tipo_backfill", _run_fallas_tipo_backfill),
        ("mandato_proyecto_backfill", _run_mandato_proyecto_backfill),
```

- [ ] **Step 3: Verificar sintaxis**

Run: `python -c "import ast; ast.parse(open('app/main.py', encoding='utf-8').read()); print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat(mandatos): run proyecto_id backfill at startup"
```

---

### Task 6: Enlazar `proyecto_id` al crear

**Files:**
- Modify: `app/api/v1/mandatos.py:29-32` (imports), `:89-100` (`crear`), `:217-221` (`upload_zip`)

- [ ] **Step 1: Añadir el import del resolver**

En `app/api/v1/mandatos.py`, después del bloque de imports de `app.services.mandatos_service` (línea 32), añadir:

```python
from app.utils.proyecto_matching import find_proyecto_by_name
```

- [ ] **Step 2: Resolver en `crear`**

En la función `crear`, reemplazar:

```python
    m = Mandato(**payload.model_dump())
    db.add(m)
```

por:

```python
    m = Mandato(**payload.model_dump())
    if m.proyecto and m.proyecto_id is None:
        proy = find_proyecto_by_name(db, m.proyecto)
        if proy:
            m.proyecto_id = proy.id
    db.add(m)
```

- [ ] **Step 3: Resolver en `upload_zip`**

En la función `upload_zip`, reemplazar:

```python
        inv_id, sugerencia, _score = match_inversionista(parsed["inversionista"], maestra)
        estado = "pendiente_envio" if inv_id else "sin_inversionista"
        m = Mandato(cmu=parsed["cmu"], periodo=p, proyecto=parsed["proyecto"],
                    tercero=parsed["inversionista"], inversionista_id=inv_id,
                    estado=estado, archivo_zip_nombre=base)
```

por:

```python
        inv_id, sugerencia, _score = match_inversionista(parsed["inversionista"], maestra)
        estado = "pendiente_envio" if inv_id else "sin_inversionista"
        proy = find_proyecto_by_name(db, parsed["proyecto"])
        m = Mandato(cmu=parsed["cmu"], periodo=p, proyecto=parsed["proyecto"],
                    proyecto_id=(proy.id if proy else None),
                    tercero=parsed["inversionista"], inversionista_id=inv_id,
                    estado=estado, archivo_zip_nombre=base)
```

- [ ] **Step 4: Verificar sintaxis del router**

Run: `python -c "import ast; ast.parse(open('app/api/v1/mandatos.py', encoding='utf-8').read()); print('ok')"`
Expected: imprime `ok`.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/mandatos.py
git commit -m "feat(mandatos): resolve proyecto_id on create and zip upload"
```

---

### Task 7: Exponer `proyecto_id` en la API (TDD)

**Files:**
- Modify: `tests/test_mandatos.py:63-73` (helper `_row`) + nuevo test
- Modify: `app/services/mandatos_service.py:60-80` (`mandato_to_dict`)

- [ ] **Step 1: Actualizar el helper `_row` y añadir el test que falla**

En `tests/test_mandatos.py`, en la función `_row`, añadir `proyecto_id=None` al dict `base` (dentro de `dict(...)`, junto a `inversionista_id=None`):

```python
        tercero="Sun-Capital", inversionista_id=None, proyecto_id=None, estado="con_correcciones",
```

Y añadir al final de la sección `mandato_to_dict` (después de `test_mandato_to_dict_fecha_inversionista_iso`, ~línea 88):

```python
def test_mandato_to_dict_incluye_proyecto_id():
    out = mandato_to_dict(_row(proyecto_id=42))
    assert out["proyecto_id"] == 42
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `pytest tests/test_mandatos.py::test_mandato_to_dict_incluye_proyecto_id -v`
Expected: FAIL con `KeyError: 'proyecto_id'`.

- [ ] **Step 3: Añadir `proyecto_id` a `mandato_to_dict`**

En `app/services/mandatos_service.py`, dentro del dict que retorna `mandato_to_dict`, después de la línea `"proyecto": row.proyecto,`, añadir:

```python
        "proyecto_id": row.proyecto_id,
```

- [ ] **Step 4: Correr los tests de mandatos y verificar que pasan**

Run: `pytest tests/test_mandatos.py -v`
Expected: todos PASS (incluye el nuevo `test_mandato_to_dict_incluye_proyecto_id`).

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos_service.py tests/test_mandatos.py
git commit -m "feat(mandatos): expose proyecto_id in mandato_to_dict"
```

---

### Task 8: Verificación final

- [ ] **Step 1: Correr toda la suite**

Run: `pytest tests/test_mandatos.py tests/test_mandato_link.py -v`
Expected: todos PASS.

- [ ] **Step 2: Verificar que la app importa (modelo + main + router juntos)**

Run: `python -c "import app.main; print('import ok')"`
Expected: imprime `import ok` sin excepción.

- [ ] **Step 3: (Opcional) Verificar Alembic offline**

Run: `alembic heads`
Expected: `047 (head)` como único head.

---

## Notas de despliegue

- Todo va por Git → Railway. Al desplegar: `start.sh` corre `alembic upgrade head` (con fallback) y el arranque provisiona la columna vía `_PENDING_DDLS` y corre el backfill vía `_deferred_init`. Los tres mecanismos son idempotentes.
- El backfill solo rellena NULLs por match exacto; nunca pisa datos ni el texto `proyecto`.
- Commits: no ejecutar los `git commit` de este plan sin confirmación del usuario y en la rama acordada (regla del repo: no commitear a `main` directamente).
