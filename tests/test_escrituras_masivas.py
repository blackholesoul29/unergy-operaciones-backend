"""Las escrituras masivas sobre tablas auditadas no pueden crecer en silencio.

Un `UPDATE ... WHERE` o un `DELETE ... WHERE` no pasa por el unit of work del
ORM, así que los hooks de `audit.py` --que escuchan `before_flush`-- no lo ven.
La tabla queda auditada sólo para quien escriba por objeto.

Así estuvo pasando `tipo_migration`: reescribía 5.086 fallas en cada arranque y
`audit_log` registró siempre a la víctima y nunca al culpable. Se descubrió por
casualidad el 2026-08-27, no porque nada lo detectara.

Este test no prohíbe el patrón --hay usos legítimos, y uno de ellos existe
justamente para no volver a causar un 504-- sino que **lo vuelve visible**:
cada sitio está declarado con su motivo, y aparecer uno nuevo rompe la suite.
Es el paso previo al hook `do_orm_execute`, que va a cerrar el agujero de
verdad; este inventario es su banco de pruebas.
"""
import pytest

from escrituras_masivas import (
    PATRON_EXECUTE, PATRON_QUERY, PATRON_TEXT,
    escanear, escanear_fuente, tablas_auditadas,
)

# (archivo, tabla) -> (cuántos sitios, por qué existen)
#
# Medido el 2026-08-27. Sólo lo que cae sobre una tabla de `_AUDITED_TABLES`:
# lo que escribe en tablas no auditadas es igual de invisible, pero ahí no hay
# auditoría que engañar.
INVENTARIO_CONOCIDO: dict[tuple[str, str], tuple[int, str]] = {
    # ── Fusión de duplicados. El caso más grave del inventario ───────────────
    # `POST /proyectos/{ganador}/merge/{perdedor}` y su gemelo de clientes
    # mueven las relaciones con UPDATE por tabla y después borran al perdedor.
    # 🛑 Incluye el ÚNICO hard-delete de un proyecto en toda la app, y no deja
    # ni una fila en audit_log: hoy, borrar un proyecto no tiene rastro.
    ("app/api/v1/proyectos.py", "proyectos"): (3, "merge: reasigna FKs y borra al perdedor"),
    ("app/api/v1/clientes.py", "clientes"): (3, "merge de clientes: limpia campos y soft-delete"),
    ("app/api/v1/clientes.py", "ppa_contratos"): (2, "merge de clientes: repunta comprador/vendedor"),

    # ── Reasignación en lote desde la UI ─────────────────────────────────────
    ("app/api/v1/comercial.py", "proyectos"): (2, "desvincula plantas de una oportunidad"),
    ("app/api/v1/portafolios.py", "proyectos"): (1, "saca las plantas de un portafolio"),
    ("app/api/v1/ppa.py", "ppa_contratos"): (1, "asigna responsable a varios PPA de una"),

    # ── Tareas de arranque. Las que más caro salen: corren en cada deploy ────
    ("app/main.py", "fallas"): (1, "tipo_migration; el bug del 2026-08-27 salió de acá"),
    ("app/main.py", "contratos_servicio"): (1, "cgm_seed repara proyecto_id cuando está NULL"),
    ("app/services/tsf_sync.py", "proyectos"): (1, "sync TSF: COALESCE masivo sobre la ficha"),
}


def _por_archivo_y_tabla():
    auditadas = tablas_auditadas()
    conteo: dict[tuple[str, str], int] = {}
    for s in escanear():
        if s.tabla in auditadas:
            conteo[(s.archivo, s.tabla)] = conteo.get((s.archivo, s.tabla), 0) + 1
    return conteo


# ── El guardián ──────────────────────────────────────────────────────────────

def test_no_aparecen_escrituras_masivas_nuevas_sobre_tablas_auditadas():
    """Si esto falla, alguien agregó una escritura que la auditoría no va a ver.

    No está mal por definición. Lo que está mal es que no se sepa: declaralo en
    INVENTARIO_CONOCIDO con el motivo, o escribí por objeto.
    """
    actual = _por_archivo_y_tabla()
    esperado = {k: v[0] for k, v in INVENTARIO_CONOCIDO.items()}

    nuevas = {k: n for k, n in actual.items()
              if k not in esperado or n > esperado[k]}

    assert not nuevas, (
        "escrituras masivas sin declarar sobre tablas auditadas:\n" +
        "\n".join(f"  {a} -> {t}: {n} sitios (declarados: {esperado.get((a, t), 0)})"
                  for (a, t), n in sorted(nuevas.items())))


def test_el_inventario_declarado_no_tiene_entradas_muertas():
    """Cuando un sitio se arregla, su línea sale del inventario.

    Sin esto, la lista se vuelve folclore: entradas que describen código que ya
    no existe y que nadie se anima a borrar.
    """
    actual = _por_archivo_y_tabla()

    muertas = {k: v for k, v in INVENTARIO_CONOCIDO.items()
               if actual.get(k, 0) < v[0]}

    assert not muertas, (
        "el inventario declara sitios que ya no existen (¿se arreglaron?):\n" +
        "\n".join(f"  {a} -> {t}: declarados {v[0]}, encontrados {actual.get((a, t), 0)}"
                  for (a, t), v in sorted(muertas.items())))


def test_el_hard_delete_de_proyectos_sigue_siendo_invisible():
    """Documenta el peor caso, para que arreglarlo sea un cambio consciente.

    Borrar un proyecto es la operación más destructiva de la app y hoy no deja
    ni una fila en `audit_log`. El día que el hook lo cubra, este test cae y hay
    que borrarlo con una sonrisa.
    """
    sitios = [s for s in escanear()
              if s.archivo == "app/api/v1/proyectos.py" and s.tabla == "proyectos"
              and "DELETE FROM proyectos" in s.fragmento]

    assert sitios, "el hard-delete de proyectos ya no aparece: ¿lo cubrió el hook?"


# ── Que el escáner detecte de verdad ─────────────────────────────────────────
# Un guardián que no ve nada pasa igual de verde que uno que funciona.

MODELOS = {"Proyecto": "proyectos", "Falla": "fallas"}


def _escanear(codigo):
    return escanear_fuente(codigo, "prueba.py", MODELOS)


def test_caza_un_update_masivo_por_query():
    sitios = _escanear("db.query(Proyecto).filter(Proyecto.id == 1).update({'x': 2})\n")

    assert len(sitios) == 1
    assert sitios[0].patron == PATRON_QUERY and sitios[0].tabla == "proyectos"


def test_caza_un_delete_masivo_por_query():
    sitios = _escanear("db.query(Falla).filter(Falla.id == 1).delete(synchronize_session=False)\n")

    assert len(sitios) == 1 and sitios[0].tabla == "fallas"


def test_caza_el_estilo_2_0():
    sitios = _escanear("db.execute(delete(Proyecto).where(Proyecto.id == 1))\n")

    assert len(sitios) == 1
    assert sitios[0].patron == PATRON_EXECUTE and sitios[0].tabla == "proyectos"


def test_caza_el_sql_crudo_con_tabla_literal():
    sitios = _escanear('db.execute(text("DELETE FROM proyectos WHERE id = :i"), p)\n')

    assert len(sitios) == 1
    assert sitios[0].patron == PATRON_TEXT and sitios[0].tabla == "proyectos"


def test_el_sql_crudo_con_tabla_interpolada_queda_sin_atribuir():
    """El patrón de los endpoints de fusión. Se reporta, pero sin tabla."""
    sitios = _escanear('db.execute(text(f"UPDATE {t} SET x=1 WHERE id=:i"), p)\n')

    assert len(sitios) == 1 and sitios[0].tabla is None


@pytest.mark.parametrize("codigo", [
    "db.delete(obj)\n",                              # por objeto: SÍ se audita
    "db.add(Proyecto(id=1))\n",
    "obj.campo = 3\n",
    "db.query(Proyecto).filter(Proyecto.id == 1).first()\n",
    "resultado.update({'x': 1})\n",                  # un dict, no una Query
    'db.execute(text("SELECT * FROM proyectos"))\n',
])
def test_no_marca_lo_que_si_pasa_por_el_orm_ni_las_lecturas(codigo):
    assert _escanear(codigo) == []
