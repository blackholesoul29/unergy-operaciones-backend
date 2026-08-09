"""Clasificación energética estandarizada (a-f): derivación de piscinas.

derivar_pools re-agrupa el dict de /cumplimiento/plantas-contratos en las 6
categorías del catálogo sin reimplementar lógica GESCON. Clave: las plantas
duplicadas salen de (a) PPA Venta y se agrupan en (c) Compra en Bolsa UNGG
por el contrato al que aportan.
"""
from app.models.clasificacion_energia import CATEGORIAS_ENERGIA, CATEGORIAS_KEYS
from app.services.clasificacion_energia import derivar_pools, _filas_desde_pools


def _data():
    return {
        "venta": [
            {"id": 1, "nombre": "Terpel 1", "comprador_nombre": "Terpel",
             "plantas": [
                 {"id": 10, "nombre": "Planta A", "codigo_sic": "700", "es_duplicado": False,
                  "fecha_inicio": "2026-01-01", "fecha_fin": "2039-12-31"},
                 {"id": 11, "nombre": "Planta B", "codigo_sic": "701", "es_duplicado": True,
                  "fecha_inicio": "2026-01-01", "fecha_fin": "2039-12-31"},
             ]},
            {"id": 2, "nombre": "NEU 1", "comprador_nombre": "NEU", "plantas": []},
        ],
        "compra": [
            {"id": 3, "nombre": "Compra UNGC", "vendedor_nombre": "UNGG",
             "plantas": [{"id": 12, "nombre": "Planta C"}]},
        ],
        "bolsa": [
            {"id": 13, "nombre": "Planta D", "piscina": "libre", "codigo_sic": None},
            {"id": 14, "nombre": "Planta E", "piscina": "comercializador", "codigo_sic": "800"},
        ],
        "bolsa_libre": [{"id": 13, "nombre": "Planta D", "piscina": "libre", "codigo_sic": None}],
        "bolsa_comercializador": [{"id": 14, "nombre": "Planta E", "piscina": "comercializador", "codigo_sic": "800"}],
    }


def test_catalogo_tiene_las_6_categorias_estables():
    assert len(CATEGORIAS_ENERGIA) == 6
    assert [c["letra"] for c in CATEGORIAS_ENERGIA] == list("abcdef")
    assert CATEGORIAS_KEYS == {
        "ppa_venta_ungg", "ppa_compra_ungc", "bolsa_compra_ungg",
        "bolsa_compra_ungc", "bolsa_venta_ungg", "bolsa_venta_ungc",
    }
    d = next(c for c in CATEGORIAS_ENERGIA if c["letra"] == "d")
    assert d["regla_pendiente"] is True


def test_duplicados_visibles_en_venta_y_agrupados_en_compra_bolsa():
    """La duplicada SÍ se lista en (a) — aporta al contrato — con su flag
    es_duplicado para el badge; y además se agrupa en (c) por contrato."""
    pools = derivar_pools(_data())["pools"]
    terpel_a = next(c for c in pools["ppa_venta_ungg"] if c["id"] == 1)
    assert [p["id"] for p in terpel_a["plantas"]] == [10, 11]
    assert [p["id"] for p in terpel_a["plantas"] if p.get("es_duplicado")] == [11]
    assert len(pools["bolsa_compra_ungg"]) == 1
    assert [p["id"] for p in pools["bolsa_compra_ungg"][0]["plantas"]] == [11]
    assert pools["bolsa_compra_ungg"][0]["id"] == 1, "agrupada por el contrato al que aporta"


def test_contrato_sin_plantas_se_conserva_en_a_pero_no_en_c():
    pools = derivar_pools(_data())["pools"]
    assert {c["id"] for c in pools["ppa_venta_ungg"]} == {1, 2}
    assert {c["id"] for c in pools["bolsa_compra_ungg"]} == {1}


def test_bolsa_se_reparte_en_e_y_f_y_d_queda_vacia():
    pools = derivar_pools(_data())["pools"]
    assert [p["id"] for p in pools["bolsa_venta_ungg"]] == [13]
    assert [p["id"] for p in pools["bolsa_venta_ungc"]] == [14]
    assert pools["bolsa_compra_ungc"] == []


def test_counts_cuentan_plantas_no_contratos():
    counts = derivar_pools(_data())["counts"]
    # (a) cuenta lo que se LISTA (incluye la duplicada con badge); la fila
    # estándar de la duplicada vive solo en (c).
    assert counts == {
        "ppa_venta_ungg": 2, "ppa_compra_ungc": 1, "bolsa_compra_ungg": 1,
        "bolsa_compra_ungc": 0, "bolsa_venta_ungg": 1, "bolsa_venta_ungc": 1,
        "ppa_compra_externa": 0,
    }


def test_fallback_sin_sublistas_de_bolsa():
    """Compat: si el backend viejo solo trae 'bolsa' con 'piscina', e/f se derivan."""
    d = _data()
    d.pop("bolsa_libre"); d.pop("bolsa_comercializador")
    pools = derivar_pools(d)["pools"]
    assert [p["id"] for p in pools["bolsa_venta_ungg"]] == [13]
    assert [p["id"] for p in pools["bolsa_venta_ungc"]] == [14]


def test_filas_para_bd_una_por_planta_categoria_contrato():
    pools = derivar_pools(_data())["pools"]
    filas = _filas_desde_pools(pools, 2026, 7)
    resumen = {(f.categoria, f.proyecto_id, f.contrato_ppa_id) for f in filas}
    assert resumen == {
        ("ppa_venta_ungg", 10, 1),
        ("ppa_compra_ungc", 12, 3),
        ("bolsa_compra_ungg", 11, 1),
        ("bolsa_venta_ungg", 13, None),
        ("bolsa_venta_ungc", 14, None),
    }
    sic = {f.proyecto_id: f.codigo_sic for f in filas}
    assert sic[10] == "700" and sic[14] == "800" and sic[13] is None


def test_snapshot_obsoleto_detecta_reglas_viejas():
    """Un mes ya materializado con reglas viejas debe recalcularse solo: si no,
    GET /clasificacion-energia contradice al tab Proyectos de Cumplimiento."""
    from datetime import datetime, timedelta, timezone
    from app.services.clasificacion_energia import (
        snapshot_obsoleto, LOGICA_ACTUALIZADA_EN,
    )

    class _Fila:
        def __init__(self, calculado_en):
            self.calculado_en = calculado_en

    assert snapshot_obsoleto(None), "sin snapshot → recalcular"
    assert snapshot_obsoleto(_Fila(None))
    assert snapshot_obsoleto(_Fila(LOGICA_ACTUALIZADA_EN - timedelta(days=1)))
    assert not snapshot_obsoleto(_Fila(LOGICA_ACTUALIZADA_EN + timedelta(days=1)))
    # SQLite devuelve datetimes naive: se asumen UTC, no deben reventar
    naive = (LOGICA_ACTUALIZADA_EN + timedelta(days=1)).replace(tzinfo=None)
    assert not snapshot_obsoleto(_Fila(naive))
