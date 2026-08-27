"""Escáner de escrituras masivas: las que `audit_log` no puede ver.

Los hooks de auditoría escuchan `before_flush`, o sea el unit of work del ORM.
Un `UPDATE ... WHERE` o un `DELETE ... WHERE` compilado por el ORM **no pasa por
ahí**: no hay objetos en `session.dirty`, así que no se audita nada.

Eso lo descubrimos por casualidad el 2026-08-27: `tipo_migration` reescribía
5.086 fallas en cada arranque y `audit_log` registró siempre a la víctima
--`fallas_tipo_backfill`, que sí escribe por objeto-- y nunca al culpable. El
patrón es invisible **por diseño**, no por un bug.

Este módulo levanta el inventario de esos sitios para que dejen de ser una
sorpresa. Lo usan `test_escrituras_masivas.py` (que falla si aparece uno nuevo
sobre una tabla auditada) y, más adelante, el banco de pruebas del hook
`do_orm_execute`.

⚠️ **Del SQL crudo por `text()` se saca la tabla sólo cuando el nombre está
escrito literal.** `UPDATE proyectos SET ...` sí; `UPDATE {t} SET ...` --el patrón
de los endpoints de fusión-- no, y esos quedan como no atribuibles. El hook
`do_orm_execute` tampoco va a poder atribuirlos: para el SQL crudo no hay
metadatos de tabla que consultar.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass

RAIZ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")

PATRON_QUERY = "Query.update/delete"      # db.query(X).filter(...).delete()
PATRON_EXECUTE = "execute(delete/update)"  # db.execute(delete(X).where(...))
PATRON_TEXT = "text() crudo"               # db.execute(text("UPDATE ..."))


@dataclass(frozen=True)
class Sitio:
    archivo: str      # relativo a la raíz del repo
    linea: int
    patron: str
    modelo: str | None
    tabla: str | None
    fragmento: str

    def __str__(self) -> str:
        donde = self.tabla or self.modelo or "?"
        return f"{self.archivo}:{self.linea}  [{self.patron}]  {donde}  {self.fragmento}"


def mapa_modelo_tabla() -> dict[str, str]:
    """Nombre de clase -> `__tablename__`, según los mappers reales.

    Se pregunta al registry y no a los archivos: contar `__tablename__` con una
    expresión regular ya me dio resultados falsos una vez en este mismo repo.
    """
    import app.models  # noqa: F401  -- registra el metadata completo
    from app.models.base import Base

    return {m.class_.__name__: m.persist_selectable.name for m in Base.registry.mappers}


def _receptor_query(nodo: ast.AST) -> str | None:
    """El modelo de la cadena `db.query(Modelo)...` que termina en este nodo.

    Devuelve None si la cadena no arranca en un `.query(...)` -- que es como se
    distingue `db.query(X).delete()` (masivo) de `db.delete(obj)` (por objeto,
    y ese sí se audita).
    """
    actual = nodo
    while isinstance(actual, (ast.Call, ast.Attribute)):
        if isinstance(actual, ast.Call):
            func = actual.func
            if isinstance(func, ast.Attribute) and func.attr == "query" and actual.args:
                arg = actual.args[0]
                if isinstance(arg, ast.Name):
                    return arg.id
                if isinstance(arg, ast.Attribute):
                    return arg.attr
                return "?"
            actual = func
        else:
            actual = actual.value
    return None


def _primer_modelo(nodo: ast.AST) -> str | None:
    """El modelo de `delete(Modelo)` / `update(Modelo)`."""
    if isinstance(nodo, ast.Call) and nodo.args:
        arg = nodo.args[0]
        if isinstance(arg, ast.Name):
            return arg.id
        if isinstance(arg, ast.Attribute):
            return arg.attr
    return None


_TABLA_EN_SQL = re.compile(
    r"\b(?:UPDATE\s+(?!SET)|DELETE\s+FROM\s+)([a-z_][a-z0-9_]*)", re.I)


def _tabla_del_sql(texto: str) -> str | None:
    """La tabla de un `UPDATE x` / `DELETE FROM x` con nombre literal.

    Devuelve None cuando el nombre viene interpolado (`UPDATE {t} SET ...`),
    que es justo el patrón de los endpoints de fusión de duplicados.
    """
    m = _TABLA_EN_SQL.search(texto)
    return m.group(1).lower() if m else None


def _fragmento(fuente: str, nodo: ast.AST) -> str:
    linea = fuente.splitlines()[nodo.lineno - 1].strip()
    return (linea[:90] + "…") if len(linea) > 90 else linea


def escanear_fuente(fuente: str, archivo: str, modelos: dict[str, str]) -> list[Sitio]:
    """Los sitios de un solo archivo. Separado para poder probarlo con texto."""
    sitios: list[Sitio] = []
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        return sitios

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
            continue
        attr = nodo.func.attr

        # 1 · db.query(Modelo)....update({...}) / .delete()
        if attr in ("update", "delete"):
            modelo = _receptor_query(nodo.func.value)
            if modelo:
                sitios.append(Sitio(archivo, nodo.lineno, PATRON_QUERY, modelo,
                                    modelos.get(modelo), _fragmento(fuente, nodo)))
                continue

        # 2 · db.execute(delete(Modelo).where(...)) — el estilo 2.0
        if attr == "execute" and nodo.args:
            interno = nodo.args[0]
            raiz = interno
            while isinstance(raiz, ast.Call) and isinstance(raiz.func, ast.Attribute):
                raiz = raiz.func.value          # desenrolla .where(...).returning(...)
            if isinstance(raiz, ast.Call) and isinstance(raiz.func, ast.Name) \
                    and raiz.func.id in ("delete", "update"):
                modelo = _primer_modelo(raiz)
                sitios.append(Sitio(archivo, nodo.lineno, PATRON_EXECUTE, modelo,
                                    modelos.get(modelo or ""), _fragmento(fuente, nodo)))
                continue

            # 3 · db.execute(text("UPDATE ...")) — ni el hook lo va a atribuir
            texto = ast.get_source_segment(fuente, interno) or ""
            if re.search(r"\b(UPDATE|DELETE\s+FROM)\b", texto, re.I):
                sitios.append(Sitio(archivo, nodo.lineno, PATRON_TEXT, None,
                                    _tabla_del_sql(texto), _fragmento(fuente, nodo)))

    return sitios


def escanear(raiz: str = RAIZ) -> list[Sitio]:
    """Todos los sitios de `app/`, ordenados por archivo y línea."""
    modelos = mapa_modelo_tabla()
    repo = os.path.dirname(raiz)
    sitios: list[Sitio] = []
    for carpeta, _, archivos in os.walk(raiz):
        for nombre in archivos:
            if not nombre.endswith(".py"):
                continue
            ruta = os.path.join(carpeta, nombre)
            rel = os.path.relpath(ruta, repo).replace("\\", "/")
            with open(ruta, encoding="utf-8") as fh:
                sitios += escanear_fuente(fh.read(), rel, modelos)
    return sorted(sitios, key=lambda s: (s.archivo, s.linea))


def tablas_auditadas() -> frozenset[str]:
    from app.services.audit import _AUDITED_TABLES
    return _AUDITED_TABLES


if __name__ == "__main__":   # inventario a mano: python tests/escrituras_masivas.py
    aud = tablas_auditadas()
    todos = escanear()
    print(f"{len(todos)} escrituras masivas en app/\n")
    for s in todos:
        marca = "🛑 AUDITADA" if s.tabla in aud else "  "
        print(f"{marca} {s}")
