"""Aplica el archivo de actualización del CRM comercial
(data/comercial_actualizacion_*.json).

Reglas que no se negocian:
  - La unión oferta↔dato es por (consecutivo, mes, año) del código. Nunca por
    nombre y nunca difusa: el fuzzy con umbral bajo ya fusionó clientes
    distintos (Soluenergías→FEM, julio 2026).
  - Lo que el archivo no nombra, no se toca.
  - Idempotente: aplicar dos veces deja el mismo resultado.
"""
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.clientes import Cliente
from app.models.comercial import (
    Oportunidad, OportunidadEstadoHistorial, OportunidadGestion, OportunidadOferta,
)
from app.services.comercial import estado_a_resultado
from app.utils.correos_hilo import codigo_partes


# Marca que va al final de CADA gestión del archivo. Es la señal de "ya
# aplicado": si existe en la bitácora, la tarea de arranque no vuelve a correr.
# Así el primer deploy aplica y los siguientes no pisan lo que el equipo
# comercial cambie a mano después.
MARCA_VERSION = "Alejandro, 2026-07-28"


def _fecha(v) -> date | None:
    return date.fromisoformat(v) if v else None


def ya_aplicado(db: Session) -> bool:
    """True si la bitácora ya tiene alguna gestión de esta actualización."""
    return (db.query(OportunidadGestion.id)
            .filter(OportunidadGestion.descripcion.like(f"%{MARCA_VERSION}%"))
            .first()) is not None


def validar(datos: dict) -> list[str]:
    """Problemas del archivo que deben verse ANTES de tocar la base."""
    problemas = []
    for i, it in enumerate(datos.get("estados", [])):
        if not it.get("gestion"):
            problemas.append(f"estados[{i}] ({it.get('codigo')}) sin gestión")
        elif MARCA_VERSION not in it["gestion"]:
            problemas.append(f"estados[{i}] ({it.get('codigo')}) sin la marca '{MARCA_VERSION}'")
    for bloque in ("envios", "estados", "eliminar"):
        for i, it in enumerate(datos.get(bloque, [])):
            if not codigo_partes(it.get("codigo", "")):
                problemas.append(f"{bloque}[{i}] con código ilegible: {it.get('codigo')!r}")
    return problemas


def indexar_por_codigo(db: Session) -> dict[tuple[int, int, int], OportunidadOferta]:
    """Todas las ofertas por las tres partes de su código. Ignora el prefijo
    ('OF.' en el seed, 'OP.' en producción) y las que no tienen código."""
    idx: dict[tuple[int, int, int], OportunidadOferta] = {}
    for o in db.query(OportunidadOferta).all():
        partes = codigo_partes(o.numero_oferta)
        if partes:
            idx[partes] = o
    return idx


def _cliente_por_nombre(db: Session, nombre: str) -> Cliente | None:
    """Búsqueda EXACTA sin distinguir mayúsculas. Deliberadamente no difusa."""
    n = (nombre or "").strip().lower()
    if not n:
        return None
    for c in db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all():
        if (c.razon_social_nombre or "").strip().lower() == n:
            return c
    return None


def _aplicar_correcciones(db, idx, items, dry_run, rep):
    """Renombres de código (los 7 años 2027 mal tecleados).

    El índice se remapea SIEMPRE, también en seco: los bloques siguientes usan
    el código ya corregido, y si en dry_run no lo remapeáramos, esos estados
    se reportarían como 'no encontrados' cuando en la corrida real sí resuelven.
    Un dry-run que da falsas alarmas no sirve para decidir.
    """
    for it in items:
        viejo = codigo_partes(it["codigo_actual"])
        o = idx.get(viejo) if viejo else None
        if not o:
            rep["no_encontrados"].append(it["codigo_actual"])
            continue
        rep["correcciones"] += 1
        nuevo = codigo_partes(it["codigo_nuevo"])
        if nuevo and nuevo != viejo:
            idx[nuevo] = idx.pop(viejo)
        if not dry_run:
            o.numero_oferta = it["codigo_nuevo"]


def _aplicar_envios(db, idx, items, dry_run, rep):
    for it in items:
        partes = codigo_partes(it["codigo"])
        o = idx.get(partes) if partes else None
        if not o:
            rep["no_encontrados"].append(it["codigo"])
            continue
        rep["envios"] += 1
        if dry_run:
            continue
        if it.get("fecha_oferta"):
            o.fecha_oferta = _fecha(it["fecha_oferta"])
        if it.get("seguimientos") is not None:
            o.seguimientos = it["seguimientos"]
        if it.get("fecha_ultima_respuesta"):
            o.fecha_ultima_respuesta = _fecha(it["fecha_ultima_respuesta"])
        if it.get("documento_url"):
            o.documento_url = it["documento_url"]
        # La planta solo se rellena si está vacía: no pisamos lo escrito a mano.
        if it.get("planta_nombre") and not o.planta_nombre:
            o.planta_nombre = it["planta_nombre"]


# El archivo de julio se escribió con el vocabulario anterior. Se traduce al
# leerlo para que siga aplicándose tal cual está en disco.
_ETAPAS_VIEJAS = {
    "prospeccion": "oportunidad",
    "envio_oferta": "oferta",
    "negociacion_contrato": "contrato",
}


def _etapa(valor: str | None) -> str | None:
    return _ETAPAS_VIEJAS.get(valor, valor)


def _etapa_de_oferta(etapa_cliente: str | None, resultado: str | None) -> str | None:
    """Etapa de UNA oferta a partir de lo que el archivo dice del negocio.

    El archivo se escribió cuando la etapa era del cliente y el detalle por
    oferta vivía en `resultado_oferta`; el caso que lo justifica es Los
    Apóstoles, donde repre/CGM cerró y la compra de energía sigue abierta. El
    resultado manda porque es el dato fino: si la oferta se aceptó queda
    firmada (u operando, si el negocio ya arrancó) y si se declinó, declinada.
    """
    etapa = _etapa(etapa_cliente)
    if resultado == "aceptado":
        return "operando" if etapa == "operando" else "firmado"
    if resultado == "declinado":
        return "declinado"
    if resultado == "pendiente" and etapa in ("firmado", "operando"):
        # El cliente cerró por otra oferta; esta sigue viva.
        return "oferta"
    return etapa


def _aplicar_estados(db, idx, items, dry_run, rep):
    """Mueve la etapa de la OFERTA (desde 2026-08-02 el estado es suyo, no del
    cliente), su resultado derivado, y deja la frase de Alejandro en la bitácora.
    La gestión no se duplica al reaplicar: se busca una idéntica en la misma
    oportunidad."""
    ahora = datetime.now(timezone.utc)
    for it in items:
        partes = codigo_partes(it["codigo"])
        o = idx.get(partes) if partes else None
        if not o:
            rep["no_encontrados"].append(it["codigo"])
            continue
        rep["estados"] += 1
        if dry_run:
            continue
        op = o.oportunidad
        # `estado_oportunidad` conserva el nombre de la llave del archivo, pero
        # ahora aterriza en la oferta que nombra el código, no en el cliente.
        nuevo = _etapa_de_oferta(it.get("estado_oportunidad"), it.get("resultado_oferta"))
        if nuevo and o.estado != nuevo:
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=op.id, oferta_id=o.id,
                estado_anterior=o.estado, estado_nuevo=nuevo))
            o.estado = nuevo
            o.estado_desde = ahora
            o.resultado = estado_a_resultado(nuevo)
        if it.get("planta_nombre") and not o.planta_nombre:
            o.planta_nombre = it["planta_nombre"]
        texto = it.get("gestion")
        if texto:
            ya = (db.query(OportunidadGestion)
                  .filter(OportunidadGestion.oportunidad_id == op.id,
                          OportunidadGestion.descripcion == texto)
                  .first())
            if not ya:
                db.add(OportunidadGestion(oportunidad_id=op.id, tipo="nota",
                                          descripcion=texto, fecha=ahora))


def _aplicar_clientes_nuevos(db, items, dry_run, rep) -> set[str]:
    """Clientes que aparecen en los correos y todavía no existen (Focusing, de
    GD La María). Solo razon_social_nombre es obligatorio; el resto se completa
    después desde /clientes. Idempotente: si ya existe, no hace nada.

    Devuelve los nombres que quedan disponibles para las ofertas nuevas de esta
    misma corrida — en seco no se escriben, pero sí cuentan, para que el reporte
    no los marque como clientes inexistentes.
    """
    disponibles: set[str] = set()
    for it in items:
        nombre = it["razon_social_nombre"]
        disponibles.add(nombre.strip().lower())
        if _cliente_por_nombre(db, nombre):
            continue
        rep["clientes_creados"] += 1
        if dry_run:
            continue
        db.add(Cliente(razon_social_nombre=nombre,
                       origen_tipo=it.get("origen_tipo"),
                       origen_detalle=it.get("origen_detalle")))
    if not dry_run:
        db.flush()
    return disponibles


def _aplicar_ofertas_nuevas(db, idx, items, dry_run, rep, clientes_disponibles=frozenset()):
    """Ofertas posteriores a la carga de julio. Idempotente por código.

    `clientes_disponibles` son los que crea el bloque clientes_nuevos en esta
    misma corrida: en seco todavía no están en la base, pero contarán cuando se
    aplique de verdad.
    """
    for it in items:
        partes = codigo_partes(it["codigo"])
        if partes and partes in idx:
            continue                      # ya existe: nada que crear
        cli = _cliente_por_nombre(db, it["cliente"])
        if not cli and it["cliente"].strip().lower() not in clientes_disponibles:
            rep["sin_resolver"].append(f"cliente inexistente: {it['cliente']}")
            continue
        rep["creadas"] += 1
        if dry_run or not cli:
            continue
        op = (db.query(Oportunidad)
              .filter(Oportunidad.cliente_id == cli.id, Oportunidad.deleted_at.is_(None))
              .order_by(Oportunidad.id).first())
        if not op:
            op = Oportunidad(cliente_id=cli.id, estado="oferta")
            db.add(op)
            db.flush()
        db.add(OportunidadOferta(
            oportunidad_id=op.id, tipo=it["tipo"], numero_oferta=it["codigo"],
            planta_nombre=it.get("planta_nombre"),
            estado="oferta", resultado="pendiente",
            fecha_oferta=_fecha(it.get("fecha_oferta")),
            seguimientos=it.get("seguimientos") or 0,
            fecha_ultima_respuesta=_fecha(it.get("fecha_ultima_respuesta")),
            documento_url=it.get("documento_url")))


def _aplicar_eliminaciones(db, idx, items, dry_run, rep):
    """BORRADO DURO: oportunidad_ofertas no tiene deleted_at, esto no se deshace.
    Por eso la fila completa se imprime antes de borrar — queda en los logs de
    Railway y se puede recrear a mano si hiciera falta."""
    for it in items:
        partes = codigo_partes(it["codigo"])
        o = idx.get(partes) if partes else None
        if not o:
            rep["no_encontrados"].append(it["codigo"])
            continue
        rep["eliminadas"] += 1
        huella = {
            "id": o.id, "oportunidad_id": o.oportunidad_id, "tipo": o.tipo,
            "numero_oferta": o.numero_oferta, "planta_nombre": o.planta_nombre,
            "precio_detalle": o.precio_detalle, "resultado": o.resultado,
            "detalle": o.detalle, "notas": o.notas, "motivo": it.get("motivo"),
        }
        rep["borradas_detalle"].append(huella)
        if not dry_run:
            print(f"[comercial_actualizacion] BORRADO DURO de oferta: {huella}")
            db.delete(o)


def _aplicar_fusiones(db, items, dry_run, rep):
    """Mueve las ofertas del cliente perdedor al ganador y da de baja al
    perdedor (soft-delete: se revierte limpiando deleted_at)."""
    ahora = datetime.now(timezone.utc)
    for it in items:
        ganador = _cliente_por_nombre(db, it["ganador"])
        perdedor = _cliente_por_nombre(db, it["perdedor"])
        if ganador and not perdedor:
            continue          # ya fusionado en una corrida anterior: nada que hacer
        if not ganador or not perdedor or ganador.id == perdedor.id:
            rep["sin_resolver"].append(f"fusion {it['perdedor']} -> {it['ganador']}")
            continue
        rep["fusiones"] += 1
        if dry_run:
            continue
        destino = (db.query(Oportunidad)
                   .filter(Oportunidad.cliente_id == ganador.id,
                           Oportunidad.deleted_at.is_(None))
                   .order_by(Oportunidad.id).first())
        if not destino:
            destino = Oportunidad(cliente_id=ganador.id, estado="oferta")
            db.add(destino)
            db.flush()
        for op in db.query(Oportunidad).filter(Oportunidad.cliente_id == perdedor.id).all():
            for of in list(op.ofertas):
                of.oportunidad_id = destino.id
            op.deleted_at = ahora
        perdedor.deleted_at = ahora


def aplicar(db: Session, datos: dict, dry_run: bool = True) -> dict:
    """Devuelve el reporte de lo que hizo (o haría, si dry_run)."""
    rep = {"envios": 0, "correcciones": 0, "estados": 0, "creadas": 0,
           "clientes_creados": 0, "eliminadas": 0, "fusiones": 0,
           "no_encontrados": [], "sin_resolver": [], "borradas_detalle": []}

    # Un solo índice para toda la corrida: las correcciones lo remapean y los
    # bloques siguientes ven ya el código nuevo, igual en seco que en real.
    idx = indexar_por_codigo(db)
    _aplicar_correcciones(db, idx, datos.get("correcciones", []), dry_run, rep)
    if not dry_run:
        db.flush()

    # Las fusiones van ANTES que los estados: mueven ofertas de una oportunidad
    # a otra, y la gestión debe quedar en la oportunidad definitiva. Al revés,
    # reaplicar creaba la nota otra vez en la oportunidad nueva.
    _aplicar_fusiones(db, datos.get("fusionar_clientes", []), dry_run, rep)
    if not dry_run:
        db.flush()

    _aplicar_envios(db, idx, datos.get("envios", []), dry_run, rep)
    _aplicar_estados(db, idx, datos.get("estados", []), dry_run, rep)
    if not dry_run:
        db.flush()

    disponibles = _aplicar_clientes_nuevos(db, datos.get("clientes_nuevos", []), dry_run, rep)
    _aplicar_ofertas_nuevas(db, idx, datos.get("ofertas_nuevas", []), dry_run, rep, disponibles)
    _aplicar_eliminaciones(db, idx, datos.get("eliminar", []), dry_run, rep)

    if not dry_run:
        db.commit()
    return rep
