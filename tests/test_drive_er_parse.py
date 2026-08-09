"""Tests del parser de nombres de Estados de Resultados en Drive.

La carpeta "Prod" nombra los archivos como
`Estado resultados {CLIENTE} {PROYECTO} {MES} {AÑO}.xlsx`; el mes y el año son
siempre los dos últimos tokens antes de la extensión. La frontera cliente/proyecto
es ambigua (los nombres de cliente traen espacios y puntos), así que el parser NO
intenta separarla: devuelve el resto como una sola descripción.
"""
from app.services.drive import parse_nombre_er


def test_nombre_tipico():
    r = parse_nombre_er("Estado resultados Ayurá S.A.S. Puya 6 2026.xlsx")
    assert r == {
        "tipo": "estado_resultados", "mes": 6, "anio": 2026,
        "descripcion": "Ayurá S.A.S. Puya", "version": None, "es_copia": False,
    }


def test_mes_de_dos_digitos():
    r = parse_nombre_er("Estado resultados Solenium S.A.S Leyenda 12 2025.xlsx")
    assert r["mes"] == 12
    assert r["anio"] == 2025


def test_proyecto_con_numeros_no_confunde_mes_y_anio():
    """`MGS 0077 - Chiriguaná Norte 4` termina en dígito: el mes/año siguen siendo
    los dos últimos tokens, y el `4` queda dentro de la descripción."""
    r = parse_nombre_er(
        "Estado resultados PATRIMONIOS AUTONOMOS SKANDIA SOCIEDAD FIDUCIARIA S.A. "
        "MGS 0077 - Chiriguaná Norte 4 6 2026.xlsx"
    )
    assert r["mes"] == 6
    assert r["anio"] == 2026
    assert r["descripcion"].endswith("Chiriguaná Norte 4")


def test_nombre_que_no_calza_devuelve_none_en_periodo():
    """Un archivo ajeno a la convención se sigue listando, pero sin período."""
    r = parse_nombre_er("Resumen consolidado.pdf")
    assert r["mes"] is None
    assert r["anio"] is None
    assert r["descripcion"] == "Resumen consolidado.pdf"


def test_mes_invalido_no_se_acepta_como_periodo():
    """`13` no es un mes; no se debe inventar un período."""
    r = parse_nombre_er("Estado resultados Demo Planta 13 2026.xlsx")
    assert r["mes"] is None
    assert r["anio"] is None


def test_extension_xls_tambien_calza():
    r = parse_nombre_er("Estado resultados Demo Planta 3 2026.xls")
    assert r["mes"] == 3
    assert r["anio"] == 2026


def test_copia_de_drive_conserva_periodo_y_se_marca():
    """~100 archivos de la carpeta son duplicados de Drive con prefijo "Copia de".
    Sin soportarlos quedarían fuera de cualquier filtro por período."""
    r = parse_nombre_er("Copia de Estado resultados Ayurá S.A.S. Puya 3 2026.xlsx")
    assert r["mes"] == 3
    assert r["anio"] == 2026
    assert r["descripcion"] == "Ayurá S.A.S. Puya"
    assert r["es_copia"] is True


def test_archivo_normal_no_se_marca_como_copia():
    r = parse_nombre_er("Estado resultados Ayurá S.A.S. Puya 3 2026.xlsx")
    assert r["es_copia"] is False


def test_no_parseable_no_se_marca_como_copia():
    r = parse_nombre_er("Resumen consolidado.pdf")
    assert r["es_copia"] is False


# ── Cruce de facturas ────────────────────────────────────────────────────────────
# La misma carpeta guarda los dos artefactos que genera la vista. El cruce se nombra
# `Cruce facturas {MES} {AÑO} {VERSION}.xlsx` y no tiene cliente ni proyecto.
def test_cruce_facturas():
    r = parse_nombre_er("Cruce facturas 1 2026 txf.xlsx")
    assert r["tipo"] == "cruce_facturas"
    assert r["mes"] == 1
    assert r["anio"] == 2026
    assert r["version"] == "txf"


def test_cruce_facturas_version_numerada():
    r = parse_nombre_er("Cruce facturas 10 2025 tx3.xlsx")
    assert r["tipo"] == "cruce_facturas"
    assert (r["mes"], r["anio"], r["version"]) == (10, 2025, "tx3")


def test_cruce_facturas_copia():
    r = parse_nombre_er("Copia de Cruce facturas 12 2025 txf.xlsx")
    assert r["tipo"] == "cruce_facturas"
    assert r["es_copia"] is True
    assert r["mes"] == 12


def test_tipo_desconocido_para_nombre_ajeno():
    r = parse_nombre_er("Resumen consolidado.pdf")
    assert r["tipo"] == "otro"
    assert r["version"] is None


def test_estado_resultados_no_trae_version():
    r = parse_nombre_er("Estado resultados Demo Planta 3 2026.xlsx")
    assert r["tipo"] == "estado_resultados"
    assert r["version"] is None
