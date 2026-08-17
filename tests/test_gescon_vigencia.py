"""resolver_vigencias: ventanas efectivas por fila de asic_solicitudes.

Caso motivador (falso positivo real, 2026-07-04): SIC 89116 (UNERGY 002-2024,
MGS 0012 La Reserva). La validación de solapamiento del GESCON comparaba la
`fecha_fin` CRUDA de filas ya superadas por una modificación que cambió la
planta del SIC — La Reserva aparecía "activa" en varios contratos a la vez
(90060, 89076, 87137) cuando en realidad fue reubicada. La ventana EFECTIVA
de la fila superada termina el día anterior al relevo → no hay cruce.

Función pura: no requiere BD — se prueba con objetos planos.
"""
from datetime import date
from types import SimpleNamespace

from app.utils.gescon_vigencia import resolver_vigencias

_next_id = iter(range(1, 10_000))


def _sol(**kw):
    kw.setdefault("id", next(_next_id))
    kw.setdefault("tipo_solicitud", "registro")
    kw.setdefault("reemplaza_anterior", True)
    kw.setdefault("proyecto_id", None)
    kw.setdefault("codigo_sic_contrato", None)
    kw.setdefault("fecha_solicitud", None)
    kw.setdefault("fecha_inicio", None)
    kw.setdefault("fecha_fin", None)
    return SimpleNamespace(**kw)


LA_RESERVA, OTRA_PLANTA, TERCERA = 101, 202, 303


# ── Caso La Reserva: reubicación de planta entre contratos ────────────────────

def _caso_la_reserva():
    """La Reserva estuvo en el SIC 87137 y fue relevada por otra planta
    (modificación reemplaza_anterior=True); hoy vive en el SIC 89116."""
    return [
        # SIC 87137: registro original de La Reserva…
        _sol(id=1, codigo_sic_contrato="87137", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2025, 4, 3), fecha_fin=date(2030, 3, 31)),
        # …relevada por OTRA planta a partir del 7-feb-2026.
        _sol(id=2, codigo_sic_contrato="87137", proyecto_id=OTRA_PLANTA,
             tipo_solicitud="modificacion", reemplaza_anterior=True,
             fecha_inicio=date(2026, 2, 7), fecha_fin=date(2030, 3, 31)),
        # SIC 89116: nuevo hogar de La Reserva desde el 7-feb-2026.
        _sol(id=3, codigo_sic_contrato="89116", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2026, 2, 7), fecha_fin=date(2039, 12, 31)),
    ]


def test_la_reserva_fila_superada_queda_recortada_al_dia_anterior_al_relevo():
    v = resolver_vigencias(_caso_la_reserva())
    assert v[1].fecha_fin_efectiva == date(2026, 2, 6), (
        "la fecha_fin CRUDA (2030) de la fila superada debe recortarse "
        "al día anterior al relevo"
    )
    assert v[1].vigente is False
    assert v[1].saliente_por_relevo is True
    assert v[1].reemplazado_por_id == 2


def test_la_reserva_ventanas_efectivas_ya_no_se_cruzan():
    """El eje del falso positivo: con ventanas efectivas, las dos filas de
    La Reserva son disjuntas (…2026-02-06] y [2026-02-07…)."""
    v = resolver_vigencias(_caso_la_reserva())
    fin_vieja = v[1].fecha_fin_efectiva
    inicio_nueva = date(2026, 2, 7)
    assert fin_vieja < inicio_nueva


def test_la_reserva_nueva_fila_y_relevo_quedan_vigentes():
    v = resolver_vigencias(_caso_la_reserva())
    assert v[3].vigente is True and v[3].fecha_fin_efectiva == date(2039, 12, 31)
    assert v[2].vigente is True


# ── Supersesión en sitio (misma planta, mismo SIC) ────────────────────────────

def test_modificacion_misma_planta_recorta_la_version_anterior():
    """Vallenata: registro 100% (2024) + modificación 50% (vigente 2026-02-12).
    La fila vieja NO es un contrato paralelo: efectiva hasta 2026-02-11."""
    regs = [
        _sol(id=10, codigo_sic_contrato="83155", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 7, 4), fecha_fin=date(2039, 12, 31)),
        _sol(id=11, codigo_sic_contrato="83155", proyecto_id=LA_RESERVA,
             tipo_solicitud="modificacion",
             fecha_inicio=date(2026, 2, 12), fecha_fin=date(2039, 12, 31)),
    ]
    v = resolver_vigencias(regs)
    assert v[10].fecha_fin_efectiva == date(2026, 2, 11)
    assert v[10].vigente is False and v[10].saliente_por_relevo is False
    assert v[10].reemplazado_por_id == 11
    assert v[11].vigente is True


# ── Coexistencia: el cruce legítimo debe seguir existiendo ────────────────────

def test_coexistencia_no_recorta_nada():
    regs = [
        _sol(id=20, codigo_sic_contrato="555", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31)),
        _sol(id=21, codigo_sic_contrato="555", proyecto_id=OTRA_PLANTA,
             reemplaza_anterior=False,
             fecha_inicio=date(2025, 6, 1), fecha_fin=date(2039, 12, 31)),
    ]
    v = resolver_vigencias(regs)
    assert v[20].vigente is True and v[20].fecha_fin_efectiva == date(2039, 12, 31)
    assert v[21].vigente is True


def test_misma_planta_en_dos_sics_sin_relevo_sigue_cruzada():
    """Control positivo: si nadie relevó a la planta en el SIC viejo, el cruce
    es REAL y las ventanas efectivas deben seguir solapándose."""
    regs = [
        _sol(id=30, codigo_sic_contrato="700", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31)),
        _sol(id=31, codigo_sic_contrato="701", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2026, 1, 1), fecha_fin=date(2039, 12, 31)),
    ]
    v = resolver_vigencias(regs)
    assert v[30].vigente is True and v[30].fecha_fin_efectiva == date(2039, 12, 31)
    assert v[31].vigente is True


# ── Relevo con coexistentes ───────────────────────────────────────────────────

def test_relevo_recorta_a_todas_las_coexistentes():
    regs = [
        _sol(id=40, codigo_sic_contrato="777", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31)),
        _sol(id=41, codigo_sic_contrato="777", proyecto_id=OTRA_PLANTA,
             reemplaza_anterior=False,
             fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31)),
        _sol(id=42, codigo_sic_contrato="777", proyecto_id=TERCERA,
             fecha_inicio=date(2026, 2, 10), fecha_fin=date(2039, 12, 31)),
    ]
    v = resolver_vigencias(regs)
    assert v[40].fecha_fin_efectiva == date(2026, 2, 9)
    assert v[41].fecha_fin_efectiva == date(2026, 2, 9)
    assert v[40].saliente_por_relevo and v[41].saliente_por_relevo
    assert v[42].vigente is True


# ── Terminación ───────────────────────────────────────────────────────────────

def test_terminacion_con_planta_cierra_esa_planta():
    """Terminaciones viejas que sí llevan proyecto_id: cierran solo esa planta."""
    regs = [
        _sol(id=50, codigo_sic_contrato="888", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2026, 8, 30)),
        _sol(id=51, codigo_sic_contrato="888", proyecto_id=LA_RESERVA,
             tipo_solicitud="terminacion",
             fecha_inicio=date(2026, 8, 31), fecha_fin=date(2026, 8, 30)),
    ]
    v = resolver_vigencias(regs)
    assert v[50].vigente is False
    assert v[50].fecha_fin_efectiva == date(2026, 8, 30)
    assert v[50].reemplazado_por_id == 51
    assert v[51].vigente is False


# Una terminación se guarda SIN proyecto_id a propósito (ver AsicTerminacionCreate).
# Hasta el 2026-08-16 el resolutor no hacía nada con ellas: confiaba en que
# `_auto_terminate` ya hubiera estampado la fecha en los registros al guardar. Eso
# se materializa una sola vez y se desincroniza — el caso real fue MGS 0008 La Paz
# Verso (terminación 202608130012), que seguía contando en su contrato.

def test_terminacion_sin_planta_cierra_todo_el_sic_aunque_no_este_estampada():
    """Con la fecha_fin cruda SIN estampar (2030), el recorte tiene que salir
    igual de la resolución: es la garantía de que no puede volver a perderse."""
    regs = [
        _sol(id=60, codigo_sic_contrato="777", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=61, codigo_sic_contrato="777", proyecto_id=OTRA_PLANTA,
             reemplaza_anterior=False,
             fecha_inicio=date(2024, 6, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=62, codigo_sic_contrato="777", tipo_solicitud="terminacion",
             fecha_inicio=None, fecha_fin=date(2026, 8, 13)),
    ]
    v = resolver_vigencias(regs)
    for fila in (60, 61):
        assert v[fila].fecha_fin_efectiva == date(2026, 8, 13)
        assert v[fila].vigente is False
        assert v[fila].reemplazado_por_id == 62
        assert v[fila].saliente_por_relevo is True, (
            "salientes, no simplemente 'no vigentes': el consumidor las prorratea "
            "hasta la fecha en vez de borrarlas del mes"
        )


def test_terminacion_no_alarga_a_quien_ya_terminaba_antes():
    regs = [
        _sol(id=63, codigo_sic_contrato="777", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2025, 6, 30)),
        _sol(id=64, codigo_sic_contrato="777", tipo_solicitud="terminacion",
             fecha_fin=date(2026, 8, 13)),
    ]
    v = resolver_vigencias(regs)
    assert v[63].fecha_fin_efectiva == date(2025, 6, 30)


def test_la_terminacion_toma_efecto_en_su_fecha_fin_no_al_principio():
    """Le va `fecha_inicio` nula: ordenada por inicio caería al principio de la
    fila —antes de que exista nada que cerrar— y no cerraría nada."""
    regs = [
        _sol(id=65, codigo_sic_contrato="776", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=66, codigo_sic_contrato="776", tipo_solicitud="terminacion",
             fecha_inicio=None, fecha_fin=date(2026, 8, 13)),
    ]
    # El orden de entrada no debe importar
    for entrada in (regs, list(reversed(regs))):
        v = resolver_vigencias(entrada)
        assert v[65].fecha_fin_efectiva == date(2026, 8, 13)


def test_un_registro_posterior_a_la_terminacion_no_se_recorta():
    """Reactivar el SIC con un registro nuevo después de cerrarlo es válido."""
    regs = [
        _sol(id=67, codigo_sic_contrato="775", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=68, codigo_sic_contrato="775", tipo_solicitud="terminacion",
             fecha_fin=date(2026, 8, 13)),
        _sol(id=69, codigo_sic_contrato="775", proyecto_id=TERCERA,
             fecha_inicio=date(2026, 9, 1), fecha_fin=date(2031, 12, 31)),
    ]
    v = resolver_vigencias(regs)
    assert v[67].fecha_fin_efectiva == date(2026, 8, 13)
    assert v[69].vigente is True
    assert v[69].fecha_fin_efectiva == date(2031, 12, 31)


def test_terminacion_sin_fecha_no_cierra_nada():
    regs = [
        _sol(id=70, codigo_sic_contrato="774", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=71, codigo_sic_contrato="774", tipo_solicitud="terminacion"),
    ]
    v = resolver_vigencias(regs)
    assert v[70].vigente is True
    assert v[70].fecha_fin_efectiva == date(2030, 12, 31)


def test_terminacion_no_afecta_los_meses_anteriores():
    regs = [
        _sol(id=72, codigo_sic_contrato="773", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=73, codigo_sic_contrato="773", tipo_solicitud="terminacion",
             fecha_fin=date(2026, 8, 13)),
    ]
    julio = resolver_vigencias(regs, hasta=date(2026, 7, 31))
    assert julio[72].vigente is True
    assert julio[72].fecha_fin_efectiva == date(2030, 12, 31)
    assert julio[73].procesado is False

    agosto = resolver_vigencias(regs, hasta=date(2026, 8, 31))
    assert agosto[72].fecha_fin_efectiva == date(2026, 8, 13)


def test_caso_la_paz_verso_la_terminacion_de_un_sic_no_toca_el_otro():
    """Verso reparte su 100% entre dos contratos (50% + 50%). Al terminarse uno,
    deja de contar ahí y sigue entera en el otro."""
    verso = 808
    regs = [
        _sol(id=80, codigo_sic_contrato="A", proyecto_id=verso,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=81, codigo_sic_contrato="B", proyecto_id=verso,
             fecha_inicio=date(2024, 1, 1), fecha_fin=date(2030, 12, 31)),
        _sol(id=82, codigo_sic_contrato="A", tipo_solicitud="terminacion",
             fecha_fin=date(2026, 8, 13)),
    ]
    v = resolver_vigencias(regs)
    assert v[80].fecha_fin_efectiva == date(2026, 8, 13)
    assert v[80].vigente is False
    assert v[81].vigente is True, "el otro contrato sigue intacto"
    assert v[81].fecha_fin_efectiva == date(2030, 12, 31)


# ── Horizonte `hasta` (vista histórica por mes) ───────────────────────────────

def test_hasta_excluye_eventos_futuros_sin_desplazar():
    """Un relevo que aún no toma efecto no debe recortar a nadie (mismo
    principio del bug histórico de _resolve_gescon)."""
    regs = _caso_la_reserva()
    v = resolver_vigencias(regs, hasta=date(2026, 1, 31))
    assert v[1].vigente is True, "en enero-2026 La Reserva seguía vigente en 87137"
    assert v[1].fecha_fin_efectiva == date(2030, 3, 31)
    assert v[2].procesado is False and v[3].procesado is False


# ── Bordes ────────────────────────────────────────────────────────────────────

def test_fecha_inicio_null_no_desborda():
    regs = [
        _sol(id=60, codigo_sic_contrato="900", proyecto_id=LA_RESERVA,
             fecha_inicio=None, fecha_fin=date(2039, 12, 31)),
        _sol(id=61, codigo_sic_contrato="900", proyecto_id=OTRA_PLANTA,
             fecha_inicio=None, fecha_fin=date(2039, 12, 31)),
    ]
    v = resolver_vigencias(regs)  # no debe lanzar OverflowError
    assert v[61].vigente is True


def test_fecha_fin_null_recortada_toma_el_corte():
    regs = [
        _sol(id=70, codigo_sic_contrato="901", proyecto_id=LA_RESERVA,
             fecha_inicio=date(2025, 1, 1), fecha_fin=None),
        _sol(id=71, codigo_sic_contrato="901", proyecto_id=OTRA_PLANTA,
             fecha_inicio=date(2026, 3, 1), fecha_fin=None),
    ]
    v = resolver_vigencias(regs)
    assert v[70].fecha_fin_efectiva == date(2026, 2, 28)
    assert v[71].fecha_fin_efectiva is None  # abierta, vigente
