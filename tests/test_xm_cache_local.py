from app.services.xm import cache_local


def test_ruta_cache_organiza_por_anio(tmp_path, monkeypatch):
    monkeypatch.setenv("XM_CACHE_DIR", str(tmp_path))
    ruta = cache_local.ruta_cache(2026, "grip0501.txf")
    assert ruta == tmp_path / "2026" / "grip0501.txf"


def test_leer_si_existe_devuelve_none_si_no_esta(tmp_path, monkeypatch):
    monkeypatch.setenv("XM_CACHE_DIR", str(tmp_path))
    assert cache_local.leer_si_existe(2026, "grip0501.txf") is None


def test_guardar_y_leer_redondo(tmp_path, monkeypatch):
    monkeypatch.setenv("XM_CACHE_DIR", str(tmp_path))
    cache_local.guardar(2026, "grip0501.txf", b"contenido de prueba")
    assert cache_local.leer_si_existe(2026, "grip0501.txf") == b"contenido de prueba"


def test_guardar_crea_carpeta_del_anio_si_no_existe(tmp_path, monkeypatch):
    monkeypatch.setenv("XM_CACHE_DIR", str(tmp_path))
    assert not (tmp_path / "2025").exists()
    cache_local.guardar(2025, "dspcttos0101.txf", b"x")
    assert (tmp_path / "2025" / "dspcttos0101.txf").is_file()


def test_carpeta_base_usa_default_si_no_hay_variable_de_entorno(monkeypatch):
    monkeypatch.delenv("XM_CACHE_DIR", raising=False)
    assert str(cache_local.carpeta_base()).endswith("Archivos_Filezilla")
