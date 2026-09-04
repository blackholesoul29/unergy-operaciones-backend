"""Consultas y armado de la respuesta del tablero de retos.

**Modelo de datos.** Un `RetoTrimestre` tiene metricas y cada metrica tiene un
valor por semana. Las semanas NO estan en la base: se derivan del rango
`fecha_inicio`/`fecha_fin` del trimestre, y cada valor queda anclado al LUNES de
su semana. Mover el rango del Q por tanto no borra nada — los valores que quedan
fuera dejan de mostrarse y vuelven si el rango se restaura.

Todo lo de aqui son funciones a nivel de modulo que reciben ids: las reusan por
igual la vista, un test y (llegado el caso) una task, porque ninguna toca
`request`. Ninguna escribe en la base.
"""

from datetime import date

from apps.retos import models as rt_models
from apps.retos.services import calculo as svc


def con_metricas_y_valores():
    """Base de toda consulta: evita el N+1 de metricas -> valores -> usuario.

    El armado recorre `reto.metricas` y, dentro, `metrica.valores`, asi que sin
    estos prefetch cada tablero costaria una consulta por metrica y otra por
    valor.
    """
    return rt_models.RetoTrimestre.objects.prefetch_related(
        "metricas",
        "metricas__valores",
        "metricas__valores__actualizado_por",
    )


def asegurar_trimestres(anio: int) -> None:
    """Autocrea los 4 trimestres calendario del año si faltan.

    `ignore_conflicts` cubre el caso de dos requests creando el mismo año en
    paralelo: la restriccion unica (anio, trimestre) lo resuelve en la base y no
    hace falta manejar la carrera aca.
    """
    existentes = set(
        rt_models.RetoTrimestre.objects.filter(anio=anio).values_list("trimestre", flat=True)
    )
    faltantes = [q for q in (1, 2, 3, 4) if q not in existentes]
    if not faltantes:
        return

    nuevos = []
    for q in faltantes:
        inicio, fin = svc.rango_trimestre(anio, q)
        nuevos.append(rt_models.RetoTrimestre(
            anio=anio, trimestre=q, nombre=svc.nombre_trimestre(anio, q),
            fecha_inicio=inicio, fecha_fin=fin,
        ))
    rt_models.RetoTrimestre.objects.bulk_create(nuevos, ignore_conflicts=True)


def anios_disponibles(anio: int) -> list[int]:
    """Los años con datos, mas el anterior y el siguiente al consultado."""
    anios = set(
        rt_models.RetoTrimestre.objects.values_list("anio", flat=True).distinct()
    )
    anios.update({anio - 1, anio, anio + 1})
    return sorted(anios)


# ---------------------------------------------------------------------------
# Armado: anota lo calculado sobre las propias instancias
# ---------------------------------------------------------------------------

def build_metrica(metrica, semanas: list[dict], corridas: int):
    """Anota consolidado, meta esperada, estado y serie sobre la metrica.

    No son datos aparte de la metrica, asi que van como atributos de la misma
    instancia y el serializer los lee por su nombre, igual que un campo real.
    """
    por_lunes = {v.semana_inicio: v for v in metrica.valores.all()}
    serie, ordenados, con_dato = [], [], 0
    for s in semanas:
        fila = por_lunes.get(s["inicio"])
        val = float(fila.valor) if (fila is not None and fila.valor is not None) else None
        if val is not None:
            con_dato += 1
        ordenados.append(val)
        serie.append({"semana": s["numero"], "valor": svc.redondear(val)})

    meta = float(metrica.meta) if metrica.meta is not None else None
    consolidado = svc.consolidar(ordenados, metrica.tipo_agregacion)
    esperada = svc.meta_esperada(meta, metrica.tipo_agregacion, corridas, len(semanas))

    metrica.meta_num = svc.redondear(meta)
    metrica.consolidado = svc.redondear(consolidado)
    metrica.meta_esperada = svc.redondear(esperada)
    metrica.avance_pct = svc.redondear(svc.avance_pct(consolidado, meta), 1)
    metrica.cumplimiento_pct = svc.redondear(
        svc.cumplimiento_pct(consolidado, esperada, metrica.direccion), 1
    )
    metrica.estado = svc.clasificar_estado(consolidado, esperada, metrica.direccion)
    metrica.semanas_con_dato = con_dato
    metrica.serie = serie
    return metrica


def build_reto(reto, hoy: date | None = None) -> tuple:
    """Devuelve (reto anotado, semanas). Las semanas las reusa el detalle."""
    hoy = hoy or date.today()
    semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, hoy)
    corridas = svc.semanas_transcurridas(semanas, reto.fecha_inicio, reto.fecha_fin, hoy)
    metricas = [build_metrica(m, semanas, corridas) for m in reto.metricas.all()]

    activas = [m for m in metricas if m.activa]
    semanas_con_datos = sum(
        1 for idx in range(len(semanas))
        if any(m.serie[idx]["valor"] is not None for m in activas)
    )

    reto.metricas_anotadas = metricas
    reto.total_semanas = len(semanas)
    reto.semana_actual = svc.numero_semana_actual(
        semanas, reto.fecha_inicio, reto.fecha_fin, hoy
    )
    reto.estado_periodo = svc.estado_periodo(reto.fecha_inicio, reto.fecha_fin, hoy)
    reto.total_metricas = len(activas)
    reto.semanas_con_datos = semanas_con_datos
    reto.avance_global_pct = svc.redondear(
        svc.promedio_cumplimiento([m.cumplimiento_pct for m in activas]), 1
    )
    return reto, semanas


def build_detalle(reto, hoy: date | None = None):
    """El reto anotado + la matriz `valores[metrica_id][lunes]` del detalle."""
    reto, semanas = build_reto(reto, hoy)
    lunes_validos = {s["inicio"] for s in semanas}

    valores: dict[str, dict] = {}
    for m in reto.metricas_anotadas:
        celdas = {}
        for v in m.valores.all():
            if v.semana_inicio not in lunes_validos:
                continue          # anclado fuera del rango actual del Q: no se muestra
            celdas[v.semana_inicio.isoformat()] = {
                "valor": svc.redondear(float(v.valor)) if v.valor is not None else None,
                "nota": v.nota,
                "actualizado_por": v.actualizado_por.nombre if v.actualizado_por else None,
                "updated_at": v.updated_at,
            }
        # La clave de la metrica se publica SIEMPRE, aunque no tenga datos, para
        # que el front indexe valores[metrica_id][semana] sin comprobar antes.
        valores[str(m.id)] = celdas

    reto.semanas = semanas
    reto.valores = valores
    return reto


def metrica_recalculada(metrica):
    """Recalcula una metrica sola contra el rango de su trimestre."""
    reto = metrica.reto
    hoy = date.today()
    semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, hoy)
    corridas = svc.semanas_transcurridas(semanas, reto.fecha_inicio, reto.fecha_fin, hoy)
    return build_metrica(metrica, semanas, corridas)
