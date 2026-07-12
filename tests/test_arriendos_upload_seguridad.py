"""Seguridad de rutas en los uploads de Arriendos.

Regresión: `codigo_contrato` y `nombre_resultante` entraban al path de escritura
sin sanitizar, permitiendo path-traversal (escritura arbitraria de archivos por
un usuario autenticado → potencial sobre-escritura de código = RCE). Estos tests
fijan el contrato de los helpers de contención dentro de `_UPLOADS_DIR`.
"""
import pytest
from fastapi import HTTPException

from app.api.v1 import arriendos

BASE = arriendos._UPLOADS_DIR.resolve()


# ── _validar_periodo: estricto YYYY-MM ─────────────────────────────────────────
@pytest.mark.parametrize("periodo", ["2026-01", "2026-12", "1999-06"])
def test_periodo_valido(periodo):
    arriendos._validar_periodo(periodo)  # no lanza


@pytest.mark.parametrize("periodo", [
    "../-01",          # traversal que el split() viejo aceptaba
    "2026-13",         # mes fuera de rango
    "2026-00",
    "2026-01-01",      # 3 componentes
    "2026/01",
    "",
    "abcd-ef",
    "2026-07\n",       # newline final: '$' lo colaba, fullmatch no
])
def test_periodo_invalido_rechazado(periodo):
    with pytest.raises(HTTPException):
        arriendos._validar_periodo(periodo)


# ── _sanit: basename seguro, sin separadores ni dot-slash ──────────────────────
@pytest.mark.parametrize("entrada", [
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "/etc/shadow",
    "....",
    "..",
    "/",
    "",
    None,
])
def test_sanit_neutraliza_traversal(entrada):
    out = arriendos._sanit(entrada)
    assert "/" not in out and "\\" not in out
    assert out not in ("", ".", "..")
    assert not out.startswith(".")


def test_sanit_conserva_nombre_normal():
    assert arriendos._sanit("COL1P2_2026-01_Juan_Proyecto.pdf") == \
        "COL1P2_2026-01_Juan_Proyecto.pdf"


def test_sanit_conserva_tildes_y_ñ():
    # Nombres legítimos del front (tildes, ñ, espacios, guiones) intactos.
    assert arriendos._sanit("CT-045_2026-03_María José Ñañez_Proyecto Ñu.pdf") == \
        "CT-045_2026-03_María José Ñañez_Proyecto Ñu.pdf"


def test_sanit_elimina_control_y_null():
    # \x00 haría fallar write_bytes con 500; se filtra junto con control chars.
    out = arriendos._sanit("foo\x00bar\t\n.pdf")
    assert "\x00" not in out and "\t" not in out and "\n" not in out
    assert out == "foobar.pdf"


def test_sanit_fallback_unico_evita_colision():
    # Dos nombres 100% basura con distinto predio/pago NO colisionan.
    a = arriendos._sanit("../", fallback="COL1P2_pago1.pdf")
    b = arriendos._sanit("..", fallback="COL9P9_pago2.pdf")
    assert a == "COL1P2_pago1.pdf" and b == "COL9P9_pago2.pdf" and a != b


# ── _dir_seguro: siempre contenido en _UPLOADS_DIR ─────────────────────────────
@pytest.mark.parametrize("codigo", [
    "CT-001",
    "../../../etc",
    "..",
    "a/../../b",
    "/absolute/evil",
])
def test_dir_seguro_contenido(codigo):
    d = arriendos._dir_seguro("2026-01", codigo).resolve()
    assert d == BASE / "2026-01" / arriendos._sanit(codigo) or BASE in d.parents
    assert str(d).startswith(str(BASE) + "/") or d == BASE
