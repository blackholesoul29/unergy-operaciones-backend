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


def test_carpeta_base_usa_la_de_jessica_si_es_su_usuario(monkeypatch):
    monkeypatch.delenv("XM_CACHE_DIR", raising=False)
    monkeypatch.setattr(cache_local, "_usuario_actual", lambda: "jessi")
    assert str(cache_local.carpeta_base()).endswith("Archivos_Filezilla")


def test_carpeta_base_usa_default_generico_para_otro_usuario(monkeypatch, tmp_path):
    monkeypatch.delenv("XM_CACHE_DIR", raising=False)
    monkeypatch.setattr(cache_local, "_usuario_actual", lambda: "juanjose")
    monkeypatch.setattr(cache_local.Path, "home", classmethod(lambda cls: tmp_path))
    assert cache_local.carpeta_base() == tmp_path / "Documentos" / "Xm" / "Archivos_Filezilla"


def test_carpeta_base_variable_de_entorno_gana_a_cualquier_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XM_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_local, "_usuario_actual", lambda: "jessi")
    assert cache_local.carpeta_base() == tmp_path
