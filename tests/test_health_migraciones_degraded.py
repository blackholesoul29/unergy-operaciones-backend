"""`/health` debe CONFESAR que las migraciones no se aplicaron.

`start.sh` arranca el servidor aunque Alembic falle (un crash-loop en el deploy es
peor que un backend degradado), pero entonces el esquema puede estar viejo. Sin esta
señal el deploy queda VERDE mientras los datos salen mal en silencio: nadie mira los
logs del contenedor, todos miran el health check.

Se prueba el helper puro (`app.core.migraciones`) y no la app entera: `app.main`
arrastra toda la cadena de routers/seguridad, que este harness no monta (ver
`conftest.py`). El cableado real —que `/health` llame al helper— se verifica leyendo
`app/main.py`.
"""
import os
import re

from app.core.migraciones import estado_salud, migraciones_fallaron

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_health_ok_cuando_las_migraciones_se_aplicaron(monkeypatch, tmp_path):
    monkeypatch.setenv("MIGRACIONES_FALLIDAS_FILE", str(tmp_path / "no-existe"))

    assert migraciones_fallaron() is False
    assert estado_salud("ops")["status"] == "ok"


def test_health_degraded_cuando_alembic_fallo(monkeypatch, tmp_path):
    marca = tmp_path / "migraciones_fallidas"
    marca.write_text("2026-07-14T12:00:00Z")
    monkeypatch.setenv("MIGRACIONES_FALLIDAS_FILE", str(marca))

    assert migraciones_fallaron() is True

    cuerpo = estado_salud("ops")
    assert cuerpo["status"] == "degraded", (
        "con migraciones sin aplicar, /health seguía diciendo 'ok' — el deploy "
        "quedaba verde con el esquema viejo."
    )
    assert "migraciones" in cuerpo


def test_health_esta_cableado_al_helper():
    """`/health` debe delegar en el helper, no reconstruir el dict a mano.

    Si alguien vuelve a poner `{"status": "ok"}` fijo en el endpoint, el backend
    miente otra vez aunque el helper esté perfecto.
    """
    with open(os.path.join(REPO_ROOT, "app", "main.py"), encoding="utf-8") as fh:
        main_py = fh.read()

    health = re.search(
        r'@app\.get\("/health"\).*?(?=\n@app\.|\Z)', main_py, re.S
    )
    assert health, "no se encontró el endpoint /health en app/main.py"
    assert "estado_salud" in health.group(0), (
        "/health no usa `estado_salud()`: volvería a reportar 'ok' con el esquema viejo."
    )


def test_start_sh_borra_la_marca_antes_de_migrar():
    """Si no se borrara, un deploy sano heredaría el 'degraded' del anterior."""
    with open(os.path.join(REPO_ROOT, "start.sh"), encoding="utf-8") as fh:
        text = fh.read()
    assert 'rm -f "$MIGRACIONES_FALLIDAS"' in text, (
        "start.sh debe limpiar la marca antes de correr alembic; si no, el "
        "backend se queda 'degraded' para siempre tras un fallo."
    )


def test_start_sh_deja_la_marca_cuando_alembic_falla():
    """El WARNING en el log no basta: debe quedar la marca que /health lee."""
    with open(os.path.join(REPO_ROOT, "start.sh"), encoding="utf-8") as fh:
        text = fh.read()
    assert re.search(r'>\s*"\$MIGRACIONES_FALLIDAS"', text), (
        "start.sh no escribe la marca al fallar alembic: el fallo volvería a ser "
        "invisible para /health."
    )
