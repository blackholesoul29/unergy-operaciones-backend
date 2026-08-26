"""Pruebas del puente contrato de representacion <-> inversionista de la planta.

El caso que manda es MGS 0024 San Diego Sur, tal como estaba en produccion:

    2026-01-01 -> 2026-02-28   Ayura 50% + Solenium 50%
    2026-03-01 -> vigente      PATRIMONIOS AUTONOMOS … - 17844 SOL DE LA SIERRA 100%

y tres contratos de representacion, los tres marcados "Vigente". Solo el de
Patrimonios deberia seguir abierto.
"""
from datetime import date
from types import SimpleNamespace

from app.services.representacion_inversionista import (
    Cierre, cierre_de, cierres_pendientes, emparejar, norm,
)

HOY = date(2026, 8, 26)


def part(cliente_id, nombre, ini, fin, pct=None):
    """Una fila de proyecto_inversionistas."""
    return SimpleNamespace(cliente_id=cliente_id, cliente_nombre=nombre,
                           fecha_inicio=ini, fecha_fin=fin,
                           porcentaje_participacion=pct)


def contrato(id, nombre_inv, inversionista_id=None, estado='vigente',
             fecha_fin=None, proyecto_id=24):
    return SimpleNamespace(id=id, inversionista_nombre=nombre_inv,
                           inversionista_id=inversionista_id, estado=estado,
                           fecha_fin=fecha_fin, proyecto_id=proyecto_id)


# ── San Diego Sur, como estaba en produccion ─────────────────────────────────
AYURA = part(101, 'Ayura S.A.S', date(2026, 1, 1), date(2026, 2, 28), 50)
SOLENIUM = part(102, 'SOLENIUM S.A.S.', date(2026, 1, 1), date(2026, 2, 28), 50)
PATRIMONIOS = part(
    103,
    'PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA'
    ' - 17844 SOL DE LA SIERRA',
    date(2026, 3, 1), None, 100)
SAN_DIEGO = [AYURA, SOLENIUM, PATRIMONIOS]


class TestEmparejar:
    def test_nombre_exacto_con_puntuacion_distinta(self):
        c = contrato(1, 'Ayura S.A.S.')          # el contrato lleva punto final
        r = emparejar(c, SAN_DIEGO)
        assert r is not None and r.cliente_id == 101
        assert r.criterio == 'nombre exacto'

    def test_mayusculas_y_tildes_no_separan(self):
        assert emparejar(contrato(2, 'solenium s.a.s'), SAN_DIEGO).cliente_id == 102

    def test_patrimonio_autonomo_por_prefijo(self):
        """El caso que rompe el match por nombre: el cliente de la planta agrega
        el fideicomiso concreto que el contrato no nombra."""
        c = contrato(3, 'PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA'
                        ' S. A. SOCIEDAD FIDUCIARIA')
        r = emparejar(c, SAN_DIEGO)
        assert r is not None and r.cliente_id == 103
        assert r.criterio == 'prefijo del nombre'

    def test_dos_fideicomisos_de_la_misma_fiduciaria_no_se_adivinan(self):
        """Con dos clientes que empiezan igual no hay forma de elegir."""
        otro = part(104,
                    'PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD'
                    ' FIDUCIARIA - 20000 OTRO FIDEICOMISO',
                    date(2026, 3, 1), None)
        c = contrato(3, 'PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A'
                        ' SOCIEDAD FIDUCIARIA')
        assert emparejar(c, [PATRIMONIOS, otro]) is None

    def test_inversionista_ajeno_a_la_planta_no_se_empareja(self):
        assert emparejar(contrato(4, 'Fonsar S.A.S.'), SAN_DIEGO) is None

    def test_sin_nombre_no_se_empareja(self):
        assert emparejar(contrato(5, None), SAN_DIEGO) is None
        assert emparejar(contrato(6, '   '), SAN_DIEGO) is None

    def test_planta_sin_inversionistas(self):
        assert emparejar(contrato(7, 'Ayura S.A.S.'), []) is None


class TestCierre:
    def test_el_de_ayura_se_cierra_con_la_fecha_de_salida(self):
        c = contrato(1, 'Ayura S.A.S.', inversionista_id=101)
        r = cierre_de(c, SAN_DIEGO, HOY)
        assert r is not None
        assert r.fecha_fin == date(2026, 2, 28)
        assert r.poner_fecha is True
        assert '2026-02-28' in r.motivo

    def test_el_de_patrimonios_sigue_abierto(self):
        """Su participacion no tiene fecha_fin: sigue vigente."""
        c = contrato(3, 'PATRIMONIOS …', inversionista_id=103)
        assert cierre_de(c, SAN_DIEGO, HOY) is None

    def test_no_pisa_una_fecha_fin_puesta_a_mano(self):
        c = contrato(1, 'Ayura', inversionista_id=101, fecha_fin=date(2026, 5, 1))
        r = cierre_de(c, SAN_DIEGO, HOY)
        assert r is not None and r.poner_fecha is False

    def test_ya_terminado_no_se_vuelve_a_cerrar(self):
        c = contrato(1, 'Ayura', inversionista_id=101, estado='terminado')
        assert cierre_de(c, SAN_DIEGO, HOY) is None

    def test_sin_vincular_no_se_toca(self):
        """Sin inversionista_id no se puede afirmar nada de su vigencia."""
        c = contrato(1, 'Ayura S.A.S.', inversionista_id=None)
        assert cierre_de(c, SAN_DIEGO, HOY) is None

    def test_participacion_que_termina_en_el_futuro_no_cierra(self):
        futura = part(200, 'Futuro S.A.S', date(2026, 1, 1), date(2027, 1, 1))
        c = contrato(9, 'Futuro S.A.S', inversionista_id=200)
        assert cierre_de(c, [futura], HOY) is None

    def test_inversionista_que_salio_y_volvio_no_cierra(self):
        """Dos periodos, el segundo abierto: el contrato sigue."""
        salio = part(300, 'Vuelve S.A.S', date(2025, 1, 1), date(2025, 6, 30))
        volvio = part(300, 'Vuelve S.A.S', date(2026, 1, 1), None)
        c = contrato(10, 'Vuelve S.A.S', inversionista_id=300)
        assert cierre_de(c, [salio, volvio], HOY) is None

    def test_dos_periodos_ambos_cerrados_toma_el_ultimo(self):
        uno = part(301, 'Dos S.A.S', date(2025, 1, 1), date(2025, 6, 30))
        dos = part(301, 'Dos S.A.S', date(2026, 1, 1), date(2026, 3, 31))
        c = contrato(11, 'Dos S.A.S', inversionista_id=301)
        r = cierre_de(c, [uno, dos], HOY)
        assert r is not None and r.fecha_fin == date(2026, 3, 31)

    def test_vinculado_a_alguien_que_no_es_inversionista_de_la_planta(self):
        """Dato incoherente: no es un contrato terminado, se deja quieto."""
        c = contrato(12, 'Ajeno', inversionista_id=999)
        assert cierre_de(c, SAN_DIEGO, HOY) is None


class TestSanDiegoSurCompleto:
    """El escenario de punta a punta: emparejar los tres y cerrar los dos que
    corresponden."""

    def test_flujo(self):
        contratos = [
            contrato(1, 'Ayura S.A.S.'),
            contrato(2, 'Solenium S.A.S.'),
            contrato(3, 'PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A'
                        ' SOCIEDAD FIDUCIARIA'),
        ]
        # 1. emparejar
        parejas = {c.id: emparejar(c, SAN_DIEGO) for c in contratos}
        assert [p.cliente_id for p in parejas.values()] == [101, 102, 103]
        for c in contratos:
            c.inversionista_id = parejas[c.id].cliente_id

        # 2. cerrar
        cierres = cierres_pendientes(contratos, {24: SAN_DIEGO}, HOY)
        assert [c.contrato_id for c in cierres] == [1, 2]
        assert all(c.fecha_fin == date(2026, 2, 28) for c in cierres)
        # el de Patrimonios, que es el unico vigente, no se toca
        assert 3 not in [c.contrato_id for c in cierres]

    def test_idempotente(self):
        """Aplicado el cierre, una segunda pasada no vuelve a proponerlo."""
        c = contrato(1, 'Ayura', inversionista_id=101)
        assert cierre_de(c, SAN_DIEGO, HOY) is not None
        c.estado = 'terminado'
        c.fecha_fin = date(2026, 2, 28)
        assert cierre_de(c, SAN_DIEGO, HOY) is None


def test_norm():
    assert norm('Ayura  S.A.S.') == norm('AYURA SAS')
    assert norm('Ayurá S.A.S') == norm('AYURA SAS')
    assert norm(None) == ''
