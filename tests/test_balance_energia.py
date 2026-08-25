"""Balance de energía en bolsa: cruce de DÍAS × PORCENTAJE de despacho.

Lo que se prueba aquí es la pieza que no existía en el módulo. Antes había dos
cálculos de bolsa incompatibles: `plantas-contratos` repartía por días (una
planta con contrato vigente todo el mes aportaba 0 a bolsa, aunque estuviera
despachada al 70%) y `energia-transada` repartía por porcentaje (sin ver los
tramos). `construir_tramos` trata los dos ejes a la vez.

Todo es función pura: sin BD, sin red, sin reloj.
"""
from datetime import date

from app.services.balance_energia import (
    _energia_proyectada,
    agregar_balance,
    calcular_balance_proyectado,
    construir_inventario,
    construir_tramos,
)

PRIMERO = date(2026, 7, 1)
ULTIMO = date(2026, 7, 31)


def _planta(pid, nombre, pct, **kw):
    fila = {
        "id": pid, "nombre": nombre, "pct_despacho": pct,
        "segmento_inicio": PRIMERO.isoformat(), "segmento_fin": ULTIMO.isoformat(),
        "es_duplicado": False, "uso_del_recurso": False, "codigo_sic": "700",
    }
    fila.update(kw)
    return fila


def _contrato(cid, nombre, plantas):
    return {"id": cid, "nombre": nombre, "comprador_nombre": "Terpel", "plantas": plantas}


def _tramos_de(data, pid):
    return construir_tramos(data, PRIMERO, ULTIMO)["plantas"][pid]["tramos"]


# ── Reparto porcentual ────────────────────────────────────────────────────────

def test_planta_al_100_no_aporta_a_bolsa():
    data = {"venta": [_contrato(1, "Terpel 1", [_planta(10, "Gandalf", 1.0)])], "bolsa": []}
    (t,) = _tramos_de(data, 10)
    assert t["pct_ppa"] == 1.0
    assert t["pct_venta_bolsa"] == 0.0


def test_despacho_parcial_manda_el_remanente_a_bolsa_ungg():
    """Regla nueva confirmada por Juan: lo que no está contratado se vende en
    bolsa por UNGG, aunque la planta tenga contrato vigente todo el mes."""
    data = {"venta": [_contrato(1, "Terpel 1", [_planta(10, "Parcial", 0.7)])], "bolsa": []}
    (t,) = _tramos_de(data, 10)
    assert t["pct_ppa"] == 0.7
    assert round(t["pct_venta_bolsa"], 6) == 0.3
    assert t["piscina_venta"] == "ungg"


def test_dos_contratos_al_50_suman_100_y_no_dejan_bolsa():
    """Caso real: Esmeralda y Vallenata, 50% Terpel 1 + 50% Terpel 2."""
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Esmeralda", 0.5)]),
            _contrato(2, "Terpel 2", [_planta(10, "Esmeralda", 0.5)]),
        ],
        "bolsa": [],
    }
    (t,) = _tramos_de(data, 10)
    assert t["pct_ppa"] == 1.0
    assert t["pct_venta_bolsa"] == 0.0


def test_duplicado_es_compra_directa_y_no_consume_generacion_propia():
    """Uruaco: registrada en Terpel 1 y 80% duplicada en Klik. El duplicado no
    baja lo que Uruaco entrega a Terpel 1 — es energía que hay que comprar."""
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Uruaco", 1.0)]),
            _contrato(2, "Klik", [_planta(10, "Uruaco", 0.8, es_duplicado=True)]),
        ],
        "bolsa": [],
    }
    (t,) = _tramos_de(data, 10)
    assert t["pct_ppa"] == 1.0
    assert t["pct_dup"] == 0.8
    assert t["pct_venta_bolsa"] == 0.0


def test_uso_del_recurso_clasifica_doble():
    """La energía se entrega al contrato (a) Y se le paga al dueño a precio de
    bolsa (c). Cuenta en pct_ppa y en pct_uso a la vez."""
    data = {
        "venta": [_contrato(1, "COX", [_planta(10, "Elektra", 1.0, uso_del_recurso=True)])],
        "bolsa": [],
    }
    (t,) = _tramos_de(data, 10)
    assert t["pct_ppa"] == 1.0
    assert t["pct_uso"] == 1.0
    assert t["pct_dup"] == 0.0
    assert t["pct_venta_bolsa"] == 0.0


# ── Tramos intra-mes ──────────────────────────────────────────────────────────

def test_planta_que_sale_de_contrato_a_mitad_de_mes_parte_en_dos_tramos():
    data = {
        "venta": [_contrato(1, "Terpel 1", [
            _planta(10, "La Perdiz", 1.0, segmento_fin="2026-07-23"),
        ])],
        "bolsa": [{"id": 10, "nombre": "La Perdiz", "piscina": "libre",
                   "segmento_inicio": "2026-07-24", "segmento_fin": "2026-07-31"}],
    }
    contratado, libre = _tramos_de(data, 10)
    assert (contratado["ini"], contratado["fin"]) == (date(2026, 7, 1), date(2026, 7, 23))
    assert contratado["pct_venta_bolsa"] == 0.0
    assert (libre["ini"], libre["fin"]) == (date(2026, 7, 24), date(2026, 7, 31))
    assert libre["pct_venta_bolsa"] == 1.0
    assert libre["piscina_venta"] == "ungg"
    assert libre["dias"] == 8


def test_segmento_comercializador_clasifica_la_venta_en_ungc():
    data = {
        "venta": [],
        "bolsa": [{"id": 10, "nombre": "Sirius", "piscina": "comercializador",
                   "codigo_sic": "890", "segmento_inicio": "2026-07-01",
                   "segmento_fin": "2026-07-31"}],
    }
    (t,) = _tramos_de(data, 10)
    assert t["pct_venta_bolsa"] == 1.0
    assert t["piscina_venta"] == "ungc"
    assert t["codigo_sic_bolsa"] == "890"


def test_remanente_porcentual_bajo_contrato_va_a_ungg_no_a_ungc():
    """Un tramo CON contrato no tiene segmento de bolsa que lo cubra, así que
    su remanente porcentual es venta directa por UNGG."""
    data = {
        "venta": [_contrato(1, "Terpel 2", [_planta(10, "Mixta", 0.6)])],
        "bolsa": [],
    }
    (t,) = _tramos_de(data, 10)
    assert t["piscina_venta"] == "ungg"
    assert round(t["pct_venta_bolsa"], 6) == 0.4


def test_dias_fuera_de_la_ventana_operativa_no_venden_en_bolsa():
    """Una planta que arranca el 10 no puede "vender el 100% en bolsa" del 1 al
    9: esos días no tiene ni asignación ni residuo, está fuera de operación."""
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Recién energizada", "piscina": "libre",
         "segmento_inicio": "2026-07-10", "segmento_fin": "2026-07-31"},
    ]}
    antes, operando = _tramos_de(data, 10)
    assert (antes["ini"], antes["fin"]) == (date(2026, 7, 1), date(2026, 7, 9))
    assert antes["operativo"] is False
    assert antes["pct_venta_bolsa"] == 0.0
    assert operando["operativo"] is True
    assert operando["pct_venta_bolsa"] == 1.0


# ── Datos sucios ──────────────────────────────────────────────────────────────

def test_porcentaje_corrupto_mayor_a_uno_se_clampa_y_se_reporta():
    data = {"venta": [_contrato(1, "Terpel 1", [_planta(10, "Corrupta", 80)])], "bolsa": []}
    out = construir_tramos(data, PRIMERO, ULTIMO)
    (t,) = out["plantas"][10]["tramos"]
    assert t["pct_ppa"] == 1.0
    assert t["pct_venta_bolsa"] == 0.0
    assert out["anomalias"] and out["anomalias"][0]["proyecto_id"] == 10


def test_suma_de_despachos_por_encima_de_100_se_reporta():
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Sobrevendida", 0.8)]),
            _contrato(2, "Terpel 2", [_planta(10, "Sobrevendida", 0.5)]),
        ],
        "bolsa": [],
    }
    out = construir_tramos(data, PRIMERO, ULTIMO)
    (t,) = out["plantas"][10]["tramos"]
    assert t["pct_ppa"] == 1.0
    assert t["pct_venta_bolsa"] == 0.0
    assert any("supera el 100%" in a["motivo"] for a in out["anomalias"])


def test_cincuenta_mas_cincuenta_no_se_reporta_como_anomalia():
    """Coma flotante: 0.5 + 0.5 no debe disparar la alerta."""
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Vallenata", 0.5)]),
            _contrato(2, "Terpel 2", [_planta(10, "Vallenata", 0.5)]),
        ],
        "bolsa": [],
    }
    assert construir_tramos(data, PRIMERO, ULTIMO)["anomalias"] == []


# ── Libro mayor ───────────────────────────────────────────────────────────────

def test_balance_netea_dentro_de_ungg_y_deja_ungc_aparte():
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Uruaco", 1.0)]),
            _contrato(2, "Klik", [_planta(10, "Uruaco", 0.8, es_duplicado=True)]),
            _contrato(3, "COX", [_planta(11, "Elektra", 1.0, uso_del_recurso=True)]),
        ],
        "bolsa": [
            {"id": 12, "nombre": "La Perdiz", "piscina": "libre",
             "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
            {"id": 13, "nombre": "Sirius", "piscina": "comercializador",
             "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
        ],
    }
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    energia = {10: {0: (100.0, 0.0)}, 11: {0: (50.0, 0.0)},
               12: {0: (400.0, 20.0)}, 13: {0: (230.0, 0.0)}}

    bal = agregar_balance(plantas, energia)

    assert bal["ungg"]["venta_bolsa"]["real"] == 400.0
    assert bal["ungg"]["venta_bolsa"]["proyectado"] == 20.0
    assert bal["ungg"]["venta_bolsa"]["total"] == 420.0
    assert bal["ungg"]["compra_bolsa_directa"]["total"] == 80.0     # 100 × 80% Klik
    assert bal["ungg"]["compra_bolsa_no_directa"]["total"] == 50.0  # Elektra
    assert bal["ungg"]["compra_bolsa_total"]["total"] == 130.0
    assert bal["ungg"]["neto"]["total"] == 290.0                    # 420 − 130
    # UNGC va aparte: no se contrarresta contra las compras de UNGG
    assert bal["ungc"]["venta_bolsa"]["total"] == 230.0


def test_balance_separa_real_de_proyectado():
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Garza", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
    ]}
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    bal = agregar_balance(plantas, {10: {0: (260.0, 50.0)}})
    venta = bal["ungg"]["venta_bolsa"]
    assert (venta["real"], venta["proyectado"], venta["total"]) == (260.0, 50.0, 310.0)
    assert venta["n_plantas"] == 1


def test_tramo_sin_generacion_no_suma_ni_cuenta_planta():
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Sin datos", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
    ]}
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    bal = agregar_balance(plantas, {})
    assert bal["ungg"]["venta_bolsa"]["total"] == 0.0
    assert bal["ungg"]["venta_bolsa"]["n_plantas"] == 0


# ── Inventario ────────────────────────────────────────────────────────────────

def test_inventario_emite_una_fila_por_rol_con_su_frontera():
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Uruaco", 1.0)]),
            _contrato(2, "Klik", [_planta(10, "Uruaco", 0.8, es_duplicado=True)]),
        ],
        "bolsa": [],
    }
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    filas = construir_inventario(plantas, {10: {0: (100.0, 0.0)}},
                                 {10: "GRANJA SOLAR URUACO"})
    por_categoria = {f["categoria"]: f for f in filas}
    assert set(por_categoria) == {"a", "c"}
    assert por_categoria["a"]["frontera"] == "GRANJA SOLAR URUACO"
    assert por_categoria["a"]["estado"] == "Registrado en Terpel 1"
    assert por_categoria["a"]["mwh_total"] == 100.0
    assert por_categoria["c"]["metodo"] == "Duplicado"
    assert por_categoria["c"]["mwh_total"] == 80.0
    assert por_categoria["c"]["desde"] == "2026-07-01"
    assert por_categoria["c"]["hasta"] == "2026-07-31"


def test_inventario_ordena_por_frontera_no_por_nombre_comercial():
    """Juan identifica las plantas por frontera; la tabla debe ordenarse así."""
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Zeta", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
        {"id": 11, "nombre": "Alfa", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
    ]}
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    filas = construir_inventario(plantas, {}, {10: "GD Aurora", 11: "GD Zafiro"})
    assert [f["frontera"] for f in filas] == ["GD Aurora", "GD Zafiro"]


def test_inventario_marca_sin_datos_en_vez_de_cero():
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Garza", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
    ]}
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    (fila,) = construir_inventario(plantas, {}, {})
    assert fila["mwh_total"] is None
    assert fila["estado"] == "Libre en UNGG"
    assert fila["frontera"] == "Garza"


# ── Orquestación (sin BD ni red) ──────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._filas


class _FakeDB:
    """Solo responde la query de Proyecto que hace calcular_balance."""

    def __init__(self, proyectos):
        self._proyectos = proyectos

    def query(self, modelo):
        from app.models.proyectos import Proyecto
        return _FakeQuery(self._proyectos if modelo is Proyecto else [])


class _P:
    def __init__(self, pid, sub_project):
        self.id = pid
        self.sub_project = sub_project


def _patch_orquestacion(monkeypatch, payload, gen_mes, rangos=None):
    from app.api.v1 import cumplimiento as cu
    from app.services import balance_energia as be

    monkeypatch.setattr(cu, "get_plantas_contratos", lambda **kw: payload)
    monkeypatch.setattr(cu, "_unergy_token", lambda: "token-falso")
    monkeypatch.setattr(cu, "_fetch_month",
                        lambda tok, sp, y, m: {"mwh": gen_mes.get(sp)})
    monkeypatch.setattr(cu, "_fetch_range",
                        lambda tok, sp, ini, fin: {"mwh": (rangos or {}).get((sp, ini, fin))})
    monkeypatch.setattr(be, "_nombre_frontera", lambda db, ids: {})


def test_calcular_balance_separa_real_y_proyectado_a_mitad_de_mes(monkeypatch):
    """26 de julio: 26 días reales + 5 proyectados con el promedio del mes."""
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "Garza", "piscina": "libre",
                   "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"}],
    }
    _patch_orquestacion(monkeypatch, payload, {"garza": 260.0})

    out = calcular_balance(_FakeDB([_P(10, "garza")]), 2026, 7, hoy=date(2026, 7, 26))

    venta = out["balance"]["ungg"]["venta_bolsa"]
    assert venta["real"] == 260.0
    assert venta["proyectado"] == 50.0    # 260/26 = 10 MWh/día × 5 días
    assert venta["total"] == 310.0
    assert out["periodo"]["dia_corte"] == 26
    assert out["periodo"]["es_mes_actual"] is True


def test_calcular_balance_mes_cerrado_no_proyecta(monkeypatch):
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "Garza", "piscina": "libre",
                   "segmento_inicio": "2026-06-01", "segmento_fin": "2026-06-30"}],
    }
    _patch_orquestacion(monkeypatch, payload, {"garza": 300.0})

    out = calcular_balance(_FakeDB([_P(10, "garza")]), 2026, 6, hoy=date(2026, 7, 26))

    venta = out["balance"]["ungg"]["venta_bolsa"]
    assert (venta["real"], venta["proyectado"], venta["total"]) == (300.0, 0.0, 300.0)


def test_calcular_balance_mes_futuro_devuelve_vacio(monkeypatch):
    from app.services.balance_energia import calcular_balance

    out = calcular_balance(_FakeDB([]), 2026, 9, hoy=date(2026, 7, 26))
    assert out["periodo"]["es_mes_futuro"] is True
    assert out["inventario"] == []
    assert out["balance"]["ungg"]["neto"]["total"] == 0.0


def test_compra_externa_en_bolsa_se_declara_y_el_toggle_la_saca(monkeypatch):
    """Agustín tiene PPA de compra externa y además cae en el residuo de bolsa:
    sin registro GESCON propio inflaría la venta en bolsa UNGG."""
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [],
        "compra_externa": [{"id": 7, "nombre": "PPA Agustín", "vendedor_nombre": "GD Agustín",
                            "fecha_inicio": "2026-01-01", "fecha_fin": "2030-12-31",
                            "plantas": [{"id": 10, "nombre": "Agustín 1",
                                         "segmento_inicio": "2026-07-01",
                                         "segmento_fin": "2026-07-31"}]}],
        "bolsa": [{"id": 10, "nombre": "Agustín 1", "piscina": "libre",
                   "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"}],
    }
    _patch_orquestacion(monkeypatch, payload, {"agustin": 120.0})
    db = _FakeDB([_P(10, "agustin")])

    incluida = calcular_balance(db, 2026, 7, hoy=date(2026, 7, 31))
    assert incluida["balance"]["ungg"]["venta_bolsa"]["total"] == 120.0
    avisos = incluida["advertencias"]["compra_externa_en_bolsa"]
    assert [a["proyecto_id"] for a in avisos] == [10]
    assert avisos[0]["mwh_total"] == 120.0

    excluida = calcular_balance(db, 2026, 7, excluir_compra_externa=True,
                                hoy=date(2026, 7, 31))
    assert excluida["balance"]["ungg"]["venta_bolsa"]["total"] == 0.0
    # La fila (g) informativa sigue estando: la planta existe, solo no pesa en bolsa
    assert [f["categoria"] for f in excluida["inventario"]] == ["g"]


def test_tramo_parcial_usa_el_rango_exacto_no_regla_de_tres(monkeypatch):
    """La planta sale de contrato el 23: los días 24-31 se piden como rango."""
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [{"id": 1, "nombre": "Terpel 1", "comprador_nombre": "Terpel",
                   "plantas": [{"id": 10, "nombre": "La Perdiz", "pct_despacho": 1.0,
                                "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-23",
                                "es_duplicado": False, "uso_del_recurso": False,
                                "codigo_sic": "700"}]}],
        "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "La Perdiz", "piscina": "libre",
                   "segmento_inicio": "2026-07-24", "segmento_fin": "2026-07-31"}],
    }
    rangos = {
        ("perdiz", date(2026, 7, 1), date(2026, 7, 23)): 230.0,
        ("perdiz", date(2026, 7, 24), date(2026, 7, 31)): 95.0,
    }
    _patch_orquestacion(monkeypatch, payload, {"perdiz": 325.0}, rangos)

    out = calcular_balance(_FakeDB([_P(10, "perdiz")]), 2026, 7, hoy=date(2026, 7, 31))

    # Solo el tramo libre entra a bolsa, con su generación real de esos 8 días
    assert out["balance"]["ungg"]["venta_bolsa"]["total"] == 95.0
    assert out["advertencias"]["tramos_estimados"] == []


def test_rango_sin_datos_se_estima_y_se_declara(monkeypatch):
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "Garza", "piscina": "libre",
                   "segmento_inicio": "2026-07-10", "segmento_fin": "2026-07-31"}],
    }
    _patch_orquestacion(monkeypatch, payload, {"garza": 310.0}, rangos={})

    out = calcular_balance(_FakeDB([_P(10, "garza")]), 2026, 7, hoy=date(2026, 7, 31))

    estimados = out["advertencias"]["tramos_estimados"]
    assert len(estimados) == 1 and estimados[0]["desde"] == "2026-07-10"
    assert out["balance"]["ungg"]["venta_bolsa"]["total"] == 220.0  # 10 MWh/día × 22


def test_sin_identificador_de_monitoreo_no_contamina_el_balance(monkeypatch):
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "Nueva", "piscina": "libre",
                   "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"}],
    }
    _patch_orquestacion(monkeypatch, payload, {})

    out = calcular_balance(_FakeDB([_P(10, None)]), 2026, 7, hoy=date(2026, 7, 31))

    assert out["balance"]["ungg"]["venta_bolsa"]["total"] == 0.0
    assert out["advertencias"]["sin_datos"][0]["motivo"] == "sin identificador de monitoreo"


def test_inventario_expone_la_generacion_base_para_auditar_el_calculo():
    """El desglose por capa tiene que mostrar el multiplicando, no solo el
    resultado: gen del tramo × % = aporte."""
    data = {
        "venta": [
            _contrato(1, "Terpel 1", [_planta(10, "Uruaco", 1.0)]),
            _contrato(2, "Klik", [_planta(10, "Uruaco", 0.8, es_duplicado=True)]),
        ],
        "bolsa": [],
    }
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    filas = construir_inventario(plantas, {10: {0: (100.0, 20.0)}}, {})
    (fila,) = [f for f in filas if f["categoria"] == "c"]
    assert fila["gen_tramo_real"] == 100.0
    assert fila["gen_tramo_proyectado"] == 20.0
    assert fila["pct"] == 0.8
    assert fila["mwh_real"] == 80.0
    assert fila["mwh_total"] == 96.0
    assert fila["estimado"] is False


def test_inventario_marca_los_tramos_estimados():
    data = {"venta": [], "bolsa": [
        {"id": 10, "nombre": "Garza", "piscina": "libre",
         "segmento_inicio": "2026-07-01", "segmento_fin": "2026-07-31"},
    ]}
    plantas = construir_tramos(data, PRIMERO, ULTIMO)["plantas"]
    (fila,) = construir_inventario(plantas, {10: {0: (100.0, 0.0)}}, {}, {(10, 0)})
    assert fila["estimado"] is True


def test_calcular_balance_marca_estimado_en_la_fila_correspondiente(monkeypatch):
    from app.services.balance_energia import calcular_balance

    payload = {
        "venta": [], "compra": [], "compra_externa": [],
        "bolsa": [{"id": 10, "nombre": "Garza", "piscina": "libre",
                   "segmento_inicio": "2026-07-10", "segmento_fin": "2026-07-31"}],
    }
    _patch_orquestacion(monkeypatch, payload, {"garza": 310.0}, rangos={})

    out = calcular_balance(_FakeDB([_P(10, "garza")]), 2026, 7, hoy=date(2026, 7, 31))

    (fila,) = [f for f in out["inventario"] if f["categoria"] == "e"]
    assert fila["estimado"] is True
    assert fila["gen_tramo_real"] == 220.0


def test_energia_proyectada_reparte_tasa_diaria_por_dias_de_tramo():
    # planta 10 con un tramo que necesita energía, del 1 al 10 (10 días), tasa 2 MWh/día
    plantas = {10: {"nombre": "X", "tramos": [
        {"ini": date(2026, 9, 1), "fin": date(2026, 9, 10),
         "pct_ppa": 0.0, "pct_dup": 0.0, "pct_uso": 0.0, "pct_venta_bolsa": 1.0,
         "piscina_venta": "ungg", "codigo_sic_bolsa": None, "asignaciones": []},
    ]}}
    energia = _energia_proyectada(plantas, {10: 2.0}, date(2026, 9, 1), date(2026, 9, 30))
    real, proy = energia[10][0]
    assert real == 0.0            # mes futuro: nada real
    assert proy == 20.0           # 2 MWh/día × 10 días


def test_calcular_balance_proyectado_usa_contratos_futuros_y_tasa(monkeypatch):
    import app.services.balance_energia as be
    # una planta al 100% en bolsa (sin contrato) todo septiembre
    data = {"venta": [], "bolsa": [{"id": 10, "nombre": "X", "pct_despacho": 1.0,
        "segmento_inicio": "2026-09-01", "segmento_fin": "2026-09-30",
        "es_duplicado": False, "uso_del_recurso": False, "codigo_sic": "700",
        "piscina": "libre"}]}
    monkeypatch.setattr(be, "_plantas_contratos_de", lambda db, y, m: data)
    monkeypatch.setattr(be, "_tasa_diaria_reciente", lambda db, plantas, hoy: {10: 3.0})

    out = calcular_balance_proyectado(db=None, year=2026, month=9, hoy=date(2026, 8, 21))
    # 30 días × 3 MWh = 90 MWh, todo venta en bolsa UNGG, proyectado
    vb = out["balance"]["ungg"]["venta_bolsa"]
    assert round(vb["total"], 1) == 90.0
    assert vb["real"] == 0.0
    assert out["periodo"]["es_proyeccion"] is True
