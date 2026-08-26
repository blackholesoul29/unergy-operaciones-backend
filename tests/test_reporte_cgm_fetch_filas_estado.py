"""fetch_filas() (reporte_cgm.py) -- distinguir "Quoia dice que no hay
reporte" de "no se pudo preguntar" (auditoría CGM 2026-08-26, finding #1).

Antes ambos casos caían en el mismo estado "Sin reporte" -- un fallo de
red/timeout hacia Quoia para una frontera un día puntual se veía IGUAL que
un día real sin reporte, sin ninguna señal para quien recibe el Excel."""
from app.services.reporte_cgm import fetch_filas


class _GaiaFake:
    def __init__(self, reporte, fallo):
        self._reporte = reporte
        self._fallo = fallo
        self.llamadas = []

    def get_border_report_status_con_estado(self, border_id, fecha_str):
        self.llamadas.append((border_id, fecha_str))
        return self._reporte, self._fallo


BORDER_META = {"id": 999, "category": 1, "name": "Test Frontera"}


def test_fallo_de_conexion_marca_estado_distinto_de_sin_reporte():
    gaia = _GaiaFake(reporte=None, fallo=True)
    filas = fetch_filas(gaia, "frt001", BORDER_META, "2026-08-25")
    assert len(filas) == 2  # main + backup
    assert all(f["state"] == "Error de conexión con Quoia" for f in filas)
    assert all(f["total reported energy"] == 0.0 for f in filas)


def test_quoia_responde_pero_sin_reporte_esa_fecha_sigue_como_sin_reporte():
    gaia = _GaiaFake(reporte=None, fallo=False)
    filas = fetch_filas(gaia, "frt001", BORDER_META, "2026-08-25")
    assert all(f["state"] == "Sin reporte" for f in filas)


def test_reporte_real_no_se_ve_afectado_por_el_flag_fallo():
    reporte = {
        "status": "OK",
        "reported_data_main": [1.0] * 24,
        "reported_data_backup": [0.5] * 24,
    }
    gaia = _GaiaFake(reporte=reporte, fallo=False)
    filas = fetch_filas(gaia, "frt001", BORDER_META, "2026-08-25")
    estados = {f["meter"]: f["state"] for f in filas}
    assert estados == {"main": "Exitoso", "backup": "Exitoso"}


def test_border_meta_none_no_llama_a_gaia_y_no_es_error_de_conexion():
    """frt_code no encontrado en el catálogo de Quoia -- comportamiento
    previo intacto, no debe confundirse con un fallo de red."""
    gaia = _GaiaFake(reporte=None, fallo=True)  # nunca se debería usar
    filas = fetch_filas(gaia, "frt001", None, "2026-08-25")
    assert not gaia.llamadas
    assert all(f["state"] == "Sin reporte" for f in filas)
