"""Tests del panel anual de cumplimiento (GET /cumplimiento/panel-anual).

El grueso apunta a `_consolidar_meses`, que es donde vive la regla de negocio:
cómo se suman N contratos en una sola serie sin que un contrato sin compromiso
arrastre el consolidado a cero, y cómo se deriva el estado del resultado.
"""

import pytest

from app.api.v1.cumplimiento import (
    _consolidar_meses,
    _sumar_opcional,
    _totales_tabla,
)


def mes(month=1, min_mwh=None, max_mwh=None, gen_mwh=0.0, valor_mwh=None,
        tipo_datos="real", plantas=None, contrato="C1", **extra):
    """Construye un mes con la forma que produce `_anual_meses_para_contrato`."""
    base = {
        "month": month,
        "min_mwh": min_mwh,
        "max_mwh": max_mwh,
        "gen_mwh": gen_mwh,
        "gen_proyectada_mwh": None,
        "gen_proyectada_cierre": None,
        "valor_mwh": valor_mwh,
        "estado": "sin_compromisos",
        "tipo_datos": tipo_datos,
        "dia_actual": None,
        "dias_restantes": None,
        "compras_bolsa_mwh": None,
        "excedentes_bolsa_mwh": None,
        "exposicion_bolsa_duplicados_mwh": None,
        "plantas": plantas if plantas is not None else [],
        "n_plantas": len(plantas) if plantas else 0,
        "_contrato_label": contrato,
    }
    base.update(extra)
    return base


def anio(**kwargs):
    """12 meses iguales, para construir un contrato de prueba rápido."""
    return [mes(month=m, **kwargs) for m in range(1, 13)]


# ── _sumar_opcional ───────────────────────────────────────────────────────────

def test_sumar_opcional_ignora_none():
    assert _sumar_opcional([10.0, None, 5.0]) == 15.0


def test_sumar_opcional_todos_none_devuelve_none():
    """Distinguir 'nadie tiene compromiso' de 'el compromiso es cero'."""
    assert _sumar_opcional([None, None]) is None


def test_sumar_opcional_lista_vacia_devuelve_none():
    assert _sumar_opcional([]) is None


def test_sumar_opcional_cero_explicito_no_es_none():
    assert _sumar_opcional([0.0, None]) == 0.0


# ── _consolidar_meses: suma de compromisos ────────────────────────────────────

def test_consolida_min_y_max_de_dos_contratos():
    a = anio(min_mwh=100.0, max_mwh=150.0, valor_mwh=120.0, gen_mwh=120.0)
    b = anio(min_mwh=50.0, max_mwh=80.0, valor_mwh=60.0, gen_mwh=60.0)

    out = _consolidar_meses([a, b])

    assert len(out) == 12
    assert out[0]["min_mwh"] == 150.0
    assert out[0]["max_mwh"] == 230.0
    assert out[0]["valor_mwh"] == 180.0
    assert out[0]["gen_mwh"] == 180.0


def test_contrato_sin_compromiso_no_arrastra_el_minimo_a_cero():
    """Un contrato con min=None no debe contar como min=0 y bajar el consolidado."""
    con_compromiso = anio(min_mwh=100.0, valor_mwh=120.0, gen_mwh=120.0)
    sin_compromiso = anio(min_mwh=None, valor_mwh=40.0, gen_mwh=40.0)

    out = _consolidar_meses([con_compromiso, sin_compromiso])

    assert out[0]["min_mwh"] == 100.0
    assert out[0]["valor_mwh"] == 160.0


def test_ningun_contrato_con_compromiso_deja_min_en_none():
    out = _consolidar_meses([anio(valor_mwh=10.0), anio(valor_mwh=20.0)])

    assert out[0]["min_mwh"] is None
    assert out[0]["max_mwh"] is None
    assert out[0]["estado"] == "sin_compromisos"


# ── _consolidar_meses: derivación del estado ──────────────────────────────────

def test_estado_ok_entre_minimo_y_maximo():
    out = _consolidar_meses([anio(min_mwh=100.0, max_mwh=200.0, valor_mwh=150.0)])

    assert out[0]["estado"] == "ok"
    assert out[0]["compras_bolsa_mwh"] == 0.0
    assert out[0]["excedentes_bolsa_mwh"] == 0.0


def test_estado_deficit_por_debajo_del_minimo():
    out = _consolidar_meses([anio(min_mwh=100.0, max_mwh=200.0, valor_mwh=70.0)])

    assert out[0]["estado"] == "deficit"
    assert out[0]["compras_bolsa_mwh"] == 30.0


def test_estado_excedente_por_encima_del_maximo():
    out = _consolidar_meses([anio(min_mwh=100.0, max_mwh=200.0, valor_mwh=260.0)])

    assert out[0]["estado"] == "excedente"
    assert out[0]["excedentes_bolsa_mwh"] == 60.0


def test_sin_maximo_nunca_hay_excedente():
    """max=None significa 'sin tope', no 'tope cero'."""
    out = _consolidar_meses([anio(min_mwh=100.0, max_mwh=None, valor_mwh=5000.0)])

    assert out[0]["estado"] == "ok"


def test_hay_compromiso_pero_no_hay_generacion_es_sin_datos():
    out = _consolidar_meses([anio(min_mwh=100.0, valor_mwh=None)])

    assert out[0]["estado"] == "sin_datos"
    assert out[0]["compras_bolsa_mwh"] is None


def test_contrato_no_vigente_no_aporta_al_consolidado():
    """Meses 'finalizado'/'no_iniciado' llegan con min/max/valor en None."""
    vigente = anio(min_mwh=100.0, valor_mwh=120.0, gen_mwh=120.0)
    terminado = anio(min_mwh=None, max_mwh=None, valor_mwh=None,
                     gen_mwh=0.0, estado="finalizado")

    out = _consolidar_meses([vigente, terminado])

    assert out[0]["min_mwh"] == 100.0
    assert out[0]["valor_mwh"] == 120.0
    assert out[0]["estado"] == "ok"


# ── déficit del consolidado vs suma de déficits ───────────────────────────────

def test_deficit_del_consolidado_difiere_de_la_suma_de_deficits():
    """Los contratos no se netean: un excedente en uno no cubre el faltante de otro.

    Consolidado: min 150, valor 150 → cumple.
    Pero el contrato A quedó 30 corto y hay que comprarlos en bolsa igual.
    """
    a = anio(min_mwh=100.0, valor_mwh=70.0, compras_bolsa_mwh=30.0, excedentes_bolsa_mwh=0.0)
    b = anio(min_mwh=50.0, max_mwh=None, valor_mwh=80.0, compras_bolsa_mwh=0.0, excedentes_bolsa_mwh=0.0)

    out = _consolidar_meses([a, b])

    assert out[0]["estado"] == "ok"
    assert out[0]["compras_bolsa_mwh"] == 0.0
    assert out[0]["suma_compras_bolsa_mwh"] == 30.0


# ── plantas y metadatos ───────────────────────────────────────────────────────

def test_plantas_se_concatenan_etiquetadas_con_su_contrato():
    a = anio(min_mwh=10.0, valor_mwh=10.0, contrato="BIA Delta 1",
             plantas=[{"nombre": "GD Delta 1", "gen_contrato_mwh": 10.0}])
    b = anio(min_mwh=20.0, valor_mwh=20.0, contrato="Terpel 8",
             plantas=[{"nombre": "Marimonda", "gen_contrato_mwh": 20.0}])

    out = _consolidar_meses([a, b])

    assert out[0]["n_plantas"] == 2
    etiquetas = {p["contrato"] for p in out[0]["plantas"]}
    assert etiquetas == {"BIA Delta 1", "Terpel 8"}


def test_no_filtra_la_clave_interna_de_etiqueta():
    out = _consolidar_meses([anio(min_mwh=10.0, valor_mwh=10.0)])

    assert "_contrato_label" not in out[0]


def test_cuenta_contratos_con_compromiso_por_mes():
    a = anio(min_mwh=100.0, valor_mwh=100.0)
    b = anio(min_mwh=None, valor_mwh=50.0)

    out = _consolidar_meses([a, b])

    assert out[0]["n_contratos_con_compromiso"] == 1


def test_exposicion_bolsa_se_suma_y_none_si_es_cero():
    con_bolsa = anio(min_mwh=10.0, valor_mwh=10.0, exposicion_bolsa_duplicados_mwh=5.0)
    sin_bolsa = anio(min_mwh=10.0, valor_mwh=10.0)

    assert _consolidar_meses([con_bolsa, sin_bolsa])[0]["exposicion_bolsa_duplicados_mwh"] == 5.0
    assert _consolidar_meses([sin_bolsa])[0]["exposicion_bolsa_duplicados_mwh"] is None


def test_sin_contratos_devuelve_lista_vacia():
    assert _consolidar_meses([]) == []


def test_conserva_tipo_datos_y_dias_del_mes_en_curso():
    a = anio(min_mwh=10.0, valor_mwh=10.0, tipo_datos="mes_actual",
             dia_actual=7, dias_restantes=24)

    out = _consolidar_meses([a])

    assert out[0]["tipo_datos"] == "mes_actual"
    assert out[0]["dia_actual"] == 7
    assert out[0]["dias_restantes"] == 24


# ── _totales_tabla ────────────────────────────────────────────────────────────

def test_totales_tabla_suma_el_anio_y_cuenta_meses_con_compromiso():
    meses = [mes(month=m, min_mwh=10.0, max_mwh=20.0) for m in range(1, 7)]
    meses += [mes(month=m) for m in range(7, 13)]

    out = _totales_tabla(meses)

    assert out["total_min_mwh"] == 60.0
    assert out["total_max_mwh"] == 120.0
    assert out["meses_con_compromisos"] == 6


def test_totales_tabla_sin_compromisos_devuelve_none_no_cero():
    out = _totales_tabla([mes(month=m) for m in range(1, 13)])

    assert out["total_min_mwh"] is None
    assert out["meses_con_compromisos"] == 0


# ── Ensamblado del endpoint (wiring), con BD y API de Unergy stubeadas ────────

class _FakeQuery:
    def filter(self, *a, **k):
        return self

    def all(self):
        return []


class _FakeDB:
    """Suficiente para el `db.query(PPACompromisoEnergia)...all()` del endpoint."""

    def query(self, *a, **k):
        return _FakeQuery()


def _contrato(id=1, nombre="BIA Delta 1", codigo="UNG-2026-018", comprador="BIA Energy"):
    from datetime import date
    from types import SimpleNamespace
    return SimpleNamespace(
        id=id, nombre_interno=nombre, numero_codigo_contrato=codigo,
        comprador_nombre=comprador,
        fecha_inicio=date(2026, 1, 1), fecha_fin=date(2030, 12, 31),
    )


@pytest.fixture
def panel(monkeypatch):
    """Llama get_panel_anual con la BD y los fetches a Unergy stubeados."""
    from app.api.v1 import cumplimiento as C

    contratos = [_contrato(1), _contrato(2, "Terpel 8", "UNG-2026-020", "Terpel")]
    monkeypatch.setattr(C, "_query_contratos_venta", lambda db, year: contratos)
    monkeypatch.setattr(C, "_resolve_gescon", lambda db, ci, y, m: [])
    monkeypatch.setattr(C, "_unergy_token", lambda: "tok")
    monkeypatch.setattr(C, "_fetch_month", lambda *a, **k: {"mwh": None, "n_records": 0, "ultimo_dia": None})
    monkeypatch.setattr(C, "_fetch_recent_avg", lambda *a, **k: {"avg_daily_mwh": None})
    C._PANEL_CACHE.clear()

    def _call(**kw):
        C._PANEL_CACHE.clear()
        return C.get_panel_anual(year=2026, db=_FakeDB(), **{
            "incluir_plantas": True, "refrescar": False, **kw, "_": None,
        })

    return _call


def test_endpoint_devuelve_consolidado_y_contratos(panel):
    out = panel()

    assert out["year"] == 2026
    assert out["consolidado"]["n_contratos"] == 2
    assert len(out["consolidado"]["meses"]) == 12
    assert len(out["contratos"]) == 2
    assert out["desde_cache"] is False


def test_cada_contrato_trae_los_campos_de_la_tabla_resumen(panel):
    c = panel()["contratos"][0]

    for campo in ("id", "nombre_interno", "numero_codigo_contrato", "comprador_nombre",
                  "fecha_inicio", "fecha_fin", "total_min_mwh", "total_max_mwh",
                  "meses_con_compromisos", "meses"):
        assert campo in c, f"falta {campo}"
    assert len(c["meses"]) == 12


def test_cada_mes_trae_los_campos_que_dibuja_la_grafica(panel):
    m = panel()["contratos"][0]["meses"][0]

    for campo in ("month", "min_mwh", "max_mwh", "gen_mwh", "valor_mwh",
                  "estado", "tipo_datos", "plantas", "n_plantas"):
        assert campo in m, f"falta {campo}"


def test_no_se_filtra_la_clave_interna_de_etiqueta(panel):
    out = panel()

    assert all("_contrato_label" not in m for m in out["contratos"][0]["meses"])
    assert all("_contrato_label" not in m for m in out["consolidado"]["meses"])


def test_incluir_plantas_false_quita_el_desglose(panel):
    out = panel(incluir_plantas=False)

    assert all("plantas" not in m for m in out["contratos"][0]["meses"])
    assert all("plantas" not in m for m in out["consolidado"]["meses"])
    # n_plantas sigue, que es barato y útil
    assert "n_plantas" in out["consolidado"]["meses"][0]


def test_segunda_llamada_sale_de_cache(monkeypatch):
    from app.api.v1 import cumplimiento as C

    contratos = [_contrato(1)]
    monkeypatch.setattr(C, "_query_contratos_venta", lambda db, year: contratos)
    monkeypatch.setattr(C, "_resolve_gescon", lambda db, ci, y, m: [])
    monkeypatch.setattr(C, "_unergy_token", lambda: "tok")
    monkeypatch.setattr(C, "_fetch_month", lambda *a, **k: {"mwh": None, "n_records": 0, "ultimo_dia": None})
    monkeypatch.setattr(C, "_fetch_recent_avg", lambda *a, **k: {"avg_daily_mwh": None})
    C._PANEL_CACHE.clear()

    primera = C.get_panel_anual(year=2026, incluir_plantas=True, refrescar=False, db=_FakeDB(), _=None)
    segunda = C.get_panel_anual(year=2026, incluir_plantas=True, refrescar=False, db=_FakeDB(), _=None)
    tercera = C.get_panel_anual(year=2026, incluir_plantas=True, refrescar=True, db=_FakeDB(), _=None)

    assert primera["desde_cache"] is False
    assert segunda["desde_cache"] is True
    assert tercera["desde_cache"] is False


def test_cache_no_mezcla_incluir_plantas(monkeypatch):
    """Distinto `incluir_plantas` = distinta clave de caché."""
    from app.api.v1 import cumplimiento as C

    monkeypatch.setattr(C, "_query_contratos_venta", lambda db, year: [_contrato(1)])
    monkeypatch.setattr(C, "_resolve_gescon", lambda db, ci, y, m: [])
    monkeypatch.setattr(C, "_unergy_token", lambda: "tok")
    monkeypatch.setattr(C, "_fetch_month", lambda *a, **k: {"mwh": None, "n_records": 0, "ultimo_dia": None})
    monkeypatch.setattr(C, "_fetch_recent_avg", lambda *a, **k: {"avg_daily_mwh": None})
    C._PANEL_CACHE.clear()

    C.get_panel_anual(year=2026, incluir_plantas=True, refrescar=False, db=_FakeDB(), _=None)
    sin_plantas = C.get_panel_anual(year=2026, incluir_plantas=False, refrescar=False, db=_FakeDB(), _=None)

    assert sin_plantas["desde_cache"] is False
    assert "plantas" not in sin_plantas["consolidado"]["meses"][0]
