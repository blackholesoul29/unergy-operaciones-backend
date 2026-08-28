"""Logica de la seccion "Registros": expediente documental por proyecto.

Sigue el patron del resto del backend: funciones a nivel de modulo, `db` como
primer parametro, `db.commit()` aqui dentro y `ValueError` para los errores de
negocio (el router los traduce a HTTP).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.proyectos import Proyecto
from app.models.registros_proyecto import (
    ArchivoDocumentoProyecto, DocumentoProyecto, EstadoDocumento, OrigenArchivo,
    ParametroProyecto,
)
from app.services.registros_proyecto import mapa_documentos as mapa
from app.services.registros_proyecto.catalogo_items import (
    ETIQUETAS_PROCESO, ITEMS, ITEMS_POR_PROCESO, Proceso, item as definicion_item,
)
from app.services.registros_proyecto.catalogo_parametros import PARAMETROS
from app.services.registros_proyecto.catalogo_parametros_cnd import (
    ETIQUETAS_GRUPO_CND, PARAMETROS_CND,
)

# Catalogo unificado: los dos procesos comparten espacio de claves a proposito,
# porque hay parametros que sirven para los dos (ver REUSADOS_DE_SIC).
DEFINICIONES: dict[str, dict] = {p["clave"]: p for p in PARAMETROS}
DEFINICIONES.update({p["clave"]: p for p in PARAMETROS_CND})

ETIQUETAS_GRUPO = {
    "novedad": "Registro de novedades",
    "frontera": "Informacion general de la frontera",
    "medidor": "Medidores",
    "tc": "Transformadores de corriente",
    "tp": "Transformadores de tension",
    "conductor": "Conductores",
    "celda": "Paneles o cajas de seguridad",
    "bornera": "Bornera de prueba",
    "modem": "Comunicaciones",
    "responsable": "Persona designada por el RF",
    **ETIQUETAS_GRUPO_CND,
}


# ---------------------------------------------------------------------------
# Catalogos (lo que la UI necesita para dibujar el timeline y los formularios)
# ---------------------------------------------------------------------------
def catalogos() -> dict:
    return {
        "procesos": [
            {"codigo": p, "etiqueta": ETIQUETAS_PROCESO[p],
             "items": len(ITEMS_POR_PROCESO[p])}
            for p in (Proceso.SIC, Proceso.CND)
        ],
        "items": [
            dict(i, parametros=mapa.parametros_de(i["proceso"], i["codigo"]))
            for i in ITEMS
        ],
        "parametros": list(DEFINICIONES.values()),
        "grupos": ETIQUETAS_GRUPO,
        "estados_documento": list(EstadoDocumento.TODOS),
    }


# ---------------------------------------------------------------------------
# Conversion de valores
# ---------------------------------------------------------------------------
def _tipar(clave: str, valor: str | None) -> tuple[Decimal | None, date | None]:
    """Deriva las columnas tipadas a partir del texto y del tipo del catalogo.

    Nunca falla: si el usuario escribio "1(10)A" en un campo declarado numerico,
    el texto se conserva intacto y la columna tipada queda vacia. Preferimos un
    filtro que no encuentra ese registro antes que un guardado que se cae.
    """
    if valor is None or valor.strip() == "":
        return None, None
    definicion = DEFINICIONES.get(clave)
    tipo = definicion["tipo"] if definicion else "TEXTO"
    texto = valor.strip()

    if tipo == "NUMERO":
        try:
            return Decimal(texto.replace(",", ".")), None
        except (InvalidOperation, ValueError):
            return None, None
    if tipo == "FECHA":
        for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return None, datetime.strptime(texto[:10], formato).date()
            except ValueError:
                continue
        return None, None
    return None, None


def _normalizar_alcance(clave: str, equipo_tipo: str | None,
                        equipo_posicion: int | None) -> tuple[str, int]:
    """Valida el alcance de un parametro contra su definicion en el catalogo."""
    definicion = DEFINICIONES.get(clave)
    if definicion is None:
        raise ValueError(f"Parametro desconocido: {clave}")

    tipo = (equipo_tipo or "").strip()
    posicion = int(equipo_posicion or 0)

    if definicion["ambito"] == "PROYECTO":
        # Un dato del proyecto no cuelga de ningun equipo: se fuerza el alcance
        # vacio para que no queden dos filas del mismo dato con alcances
        # distintos y la restriccion de unicidad deje de servir.
        return "", 0

    permitidos = definicion.get("equipo_tipos") or []
    if permitidos and tipo not in permitidos:
        raise ValueError(
            f"{clave} no aplica al equipo {tipo!r}; esperado uno de {permitidos}")
    if posicion < 0 or posicion > definicion.get("instancias", 1):
        raise ValueError(
            f"{clave}: posicion {posicion} fuera de rango "
            f"(1..{definicion.get('instancias', 1)})")
    return tipo, max(posicion, 1)


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
def _verificar_proyecto(db: Session, proyecto_id: int) -> Proyecto:
    proyecto = db.get(Proyecto, proyecto_id)
    if proyecto is None:
        raise ValueError(f"Proyecto {proyecto_id} no existe")
    return proyecto


def get_or_create_documento(db: Session, proyecto_id: int, proceso: str,
                            item_codigo: str) -> DocumentoProyecto:
    if definicion_item(proceso, item_codigo) is None:
        raise ValueError(f"El item {proceso} {item_codigo} no existe en el catalogo")
    _verificar_proyecto(db, proyecto_id)

    doc = db.scalar(
        select(DocumentoProyecto).where(
            DocumentoProyecto.proyecto_id == proyecto_id,
            DocumentoProyecto.proceso == proceso,
            DocumentoProyecto.item_codigo == item_codigo,
        )
    )
    if doc is None:
        doc = DocumentoProyecto(proyecto_id=proyecto_id, proceso=proceso,
                                item_codigo=item_codigo,
                                estado=EstadoDocumento.PENDIENTE)
        db.add(doc)
        db.commit()
        db.refresh(doc)
    return doc


def actualizar_documento(db: Session, doc: DocumentoProyecto, campos: dict) -> DocumentoProyecto:
    if "estado" in campos and campos["estado"] not in EstadoDocumento.TODOS:
        raise ValueError(f"Estado invalido: {campos['estado']}")
    for k, v in campos.items():
        setattr(doc, k, v)
    db.commit()
    db.refresh(doc)
    return doc


def agregar_archivo(db: Session, doc: DocumentoProyecto, datos: dict) -> ArchivoDocumentoProyecto:
    definicion = definicion_item(doc.proceso, doc.item_codigo)
    if definicion and not definicion.get("multiple") and doc.archivos:
        raise ValueError(
            f"El item {doc.proceso} {doc.item_codigo} admite un solo archivo; "
            "elimine el actual antes de montar otro")
    origen = datos.get("origen") or OrigenArchivo.LINK
    if origen not in OrigenArchivo.TODOS:
        raise ValueError(f"Origen invalido: {origen}")

    archivo = ArchivoDocumentoProyecto(documento_id=doc.id, **{**datos, "origen": origen})
    db.add(archivo)
    # Montar un archivo es lo que marca la casilla como cargada: el estado se
    # deriva de los hechos, no lo mantiene el usuario a mano.
    if doc.estado == EstadoDocumento.PENDIENTE:
        doc.estado = EstadoDocumento.CARGADO
    db.commit()
    db.refresh(archivo)
    return archivo


def eliminar_archivo(db: Session, archivo: ArchivoDocumentoProyecto) -> None:
    doc = db.get(DocumentoProyecto, archivo.documento_id)
    db.delete(archivo)
    db.flush()
    if doc is not None and not doc.archivos and doc.estado == EstadoDocumento.CARGADO:
        doc.estado = EstadoDocumento.PENDIENTE
    db.commit()


# ---------------------------------------------------------------------------
# Parametros
# ---------------------------------------------------------------------------
def listar_parametros(db: Session, proyecto_id: int) -> list[ParametroProyecto]:
    return list(db.scalars(
        select(ParametroProyecto)
        .where(ParametroProyecto.proyecto_id == proyecto_id)
        .order_by(ParametroProyecto.clave, ParametroProyecto.equipo_tipo,
                  ParametroProyecto.equipo_posicion)
    ))


def guardar_parametros(db: Session, proyecto_id: int, valores: list[dict],
                       actor: str | None = None) -> list[ParametroProyecto]:
    """Crea o actualiza valores. Un dato ya existente se actualiza, no se duplica.

    Esta funcion es el punto donde se cumple la regla del modulo: la busqueda
    por (proyecto, clave, equipo_tipo, posicion) antes de insertar es lo que
    impide que el mismo dato entre dos veces por venir de dos documentos.
    """
    _verificar_proyecto(db, proyecto_id)
    guardados: list[ParametroProyecto] = []

    for entrada in valores:
        clave = (entrada.get("clave") or "").strip()
        tipo, posicion = _normalizar_alcance(
            clave, entrada.get("equipo_tipo"), entrada.get("equipo_posicion"))

        fila = db.scalar(
            select(ParametroProyecto).where(
                ParametroProyecto.proyecto_id == proyecto_id,
                ParametroProyecto.clave == clave,
                ParametroProyecto.equipo_tipo == tipo,
                ParametroProyecto.equipo_posicion == posicion,
            )
        )
        if fila is None:
            fila = ParametroProyecto(proyecto_id=proyecto_id, clave=clave,
                                     equipo_tipo=tipo, equipo_posicion=posicion)
            db.add(fila)

        if "valor" in entrada:
            fila.valor = entrada["valor"]
            fila.valor_numero, fila.valor_fecha = _tipar(clave, entrada["valor"])
        for campo in ("documento_origen_id", "verificado", "notas"):
            if campo in entrada:
                setattr(fila, campo, entrada[campo])
        fila.actualizado_por = actor
        guardados.append(fila)

    db.commit()
    for fila in guardados:
        db.refresh(fila)
    return guardados


def eliminar_parametro(db: Session, parametro: ParametroProyecto) -> None:
    db.delete(parametro)
    db.commit()


# ---------------------------------------------------------------------------
# Vistas compuestas
# ---------------------------------------------------------------------------
def _indice_valores(db: Session, proyecto_id: int) -> dict[tuple[str, str, int], ParametroProyecto]:
    return {(p.clave, p.equipo_tipo, p.equipo_posicion): p
            for p in listar_parametros(db, proyecto_id)}


def _instancias(definicion: dict) -> list[tuple[str, int, str]]:
    """Expande una definicion en sus instancias concretas (equipo, posicion, etiqueta)."""
    if definicion["ambito"] == "PROYECTO":
        return [("", 0, "")]
    salida = []
    for equipo in definicion.get("equipo_tipos") or [""]:
        total = definicion.get("instancias", 1)
        etiquetas = definicion.get("etiquetas") or []
        for i in range(1, total + 1):
            etiqueta = etiquetas[i - 1] if i - 1 < len(etiquetas) else (
                f"{equipo} {i}" if total > 1 else equipo)
            salida.append((equipo, i, etiqueta))
    return salida


def formulario_item(db: Session, proyecto_id: int, proceso: str,
                    item_codigo: str) -> dict:
    """Todo lo necesario para diligenciar un item: la casilla, sus archivos y sus campos.

    Cada campo viene con `tambien_en`: los otros documentos del expediente donde
    ese mismo dato aparece. Es la explicacion que el usuario necesita para
    entender por que solo lo escribe una vez.
    """
    definicion = definicion_item(proceso, item_codigo)
    if definicion is None:
        raise ValueError(f"El item {proceso} {item_codigo} no existe en el catalogo")

    doc = get_or_create_documento(db, proyecto_id, proceso, item_codigo)
    valores = _indice_valores(db, proyecto_id)

    campos = []
    for clave in mapa.parametros_de(proceso, item_codigo):
        d = DEFINICIONES.get(clave)
        if d is None:
            continue
        otros = [{"proceso": p, "item": c}
                 for p, c in mapa.items_que_usan(clave)
                 if (p, c) != (proceso, item_codigo)]
        for equipo, posicion, etiqueta in _instancias(d):
            fila = valores.get((clave, equipo, posicion))
            campos.append({
                "clave": clave,
                "titulo": d["titulo"],
                "tipo": d["tipo"],
                "unidad": d.get("unidad", ""),
                "grupo": d["grupo"],
                "grupo_etiqueta": ETIQUETAS_GRUPO.get(d["grupo"], d["grupo"]),
                "requerido": d["requerido"],
                "columnas": d.get("columnas"),
                "equipo_tipo": equipo,
                "equipo_posicion": posicion,
                "equipo_etiqueta": etiqueta,
                "valor": fila.valor if fila else None,
                "verificado": bool(fila.verificado) if fila else False,
                "documento_origen_id": fila.documento_origen_id if fila else None,
                "diligenciado_en_otro_documento": bool(
                    fila and fila.valor not in (None, "")
                    and fila.documento_origen_id not in (None, doc.id)),
                "tambien_en": otros,
            })

    return {
        "documento": doc,
        "item": definicion,
        "campos": campos,
        "total_campos": len(campos),
        "campos_diligenciados": sum(1 for c in campos if c["valor"] not in (None, "")),
    }


def listar_proyectos(db: Session) -> list[dict]:
    """Indice de la seccion: un proyecto por fila con el avance de cada proceso.

    Se resuelve con dos agregados en vez de armar el resumen completo de cada
    proyecto: la vista solo necesita cuantas casillas van cargadas, y hacerlo
    proyecto por proyecto seria una consulta por fila.
    """
    total_items = {p: len(ITEMS_POR_PROCESO[p]) for p in (Proceso.SIC, Proceso.CND)}

    cargados: dict[tuple[int, str], int] = {}
    no_aplica: dict[tuple[int, str], int] = {}
    for proyecto_id, proceso, estado, cuantos in db.execute(
        select(DocumentoProyecto.proyecto_id, DocumentoProyecto.proceso,
               DocumentoProyecto.estado, func.count())
        .group_by(DocumentoProyecto.proyecto_id, DocumentoProyecto.proceso,
                  DocumentoProyecto.estado)
    ):
        if estado == EstadoDocumento.CARGADO:
            cargados[(proyecto_id, proceso)] = cuantos
        elif estado == EstadoDocumento.NO_APLICA:
            no_aplica[(proyecto_id, proceso)] = cuantos

    con_valor: dict[int, int] = dict(db.execute(
        select(ParametroProyecto.proyecto_id, func.count())
        .where(ParametroProyecto.valor.isnot(None), ParametroProyecto.valor != "")
        .group_by(ParametroProyecto.proyecto_id)
    ).all())

    consulta = select(Proyecto)
    if hasattr(Proyecto, "deleted_at"):
        consulta = consulta.where(Proyecto.deleted_at.is_(None))

    filas = []
    for proyecto in db.scalars(consulta.order_by(Proyecto.nombre_comercial)):
        avances = {}
        for codigo_proceso in (Proceso.SIC, Proceso.CND):
            aplicables = (total_items[codigo_proceso]
                          - no_aplica.get((proyecto.id, codigo_proceso), 0))
            listos = cargados.get((proyecto.id, codigo_proceso), 0)
            avances[codigo_proceso] = {
                "cargados": listos,
                "total": aplicables,
                "pct": round(100 * listos / aplicables) if aplicables else 0,
            }
        filas.append({
            "proyecto_id": proyecto.id,
            "nombre_comercial": proyecto.nombre_comercial,
            "codigo_cnd": getattr(proyecto, "codigo_cnd", None),
            "sic": avances[Proceso.SIC],
            "cnd": avances[Proceso.CND],
            "parametros_diligenciados": con_valor.get(proyecto.id, 0),
        })
    return filas


def resumen_proyecto(db: Session, proyecto_id: int, proceso: str | None = None) -> dict:
    """Timeline del expediente: cada item con su estado, archivos y avance de datos."""
    proyecto = _verificar_proyecto(db, proyecto_id)

    docs = {(d.proceso, d.item_codigo): d for d in db.scalars(
        select(DocumentoProyecto)
        .options(selectinload(DocumentoProyecto.archivos))
        .where(DocumentoProyecto.proyecto_id == proyecto_id)
    )}
    valores = _indice_valores(db, proyecto_id)
    llenos = {k for k, v in valores.items() if v.valor not in (None, "")}

    procesos = [proceso] if proceso else [Proceso.SIC, Proceso.CND]
    salida = []
    for codigo_proceso in procesos:
        items = []
        for definicion in ITEMS_POR_PROCESO[codigo_proceso]:
            doc = docs.get((codigo_proceso, definicion["codigo"]))
            claves = mapa.parametros_de(codigo_proceso, definicion["codigo"])

            esperados = diligenciados = 0
            for clave in claves:
                d = DEFINICIONES.get(clave)
                if d is None:
                    continue
                for equipo, posicion, _ in _instancias(d):
                    esperados += 1
                    if (clave, equipo, posicion) in llenos:
                        diligenciados += 1

            items.append({
                "proceso": codigo_proceso,
                "codigo": definicion["codigo"],
                "titulo": definicion["titulo"],
                "descripcion": definicion["descripcion"],
                "emisor": definicion["emisor"],
                "multiple": definicion["multiple"],
                "estado_base": definicion["estado_base"],
                "nota_catalogo": definicion.get("nota"),
                "documento_id": doc.id if doc else None,
                "estado": doc.estado if doc else EstadoDocumento.PENDIENTE,
                "radicado": doc.radicado if doc else None,
                "fecha_emision": doc.fecha_emision if doc else None,
                "archivos": len(doc.archivos) if doc else 0,
                "parametros_esperados": esperados,
                "parametros_diligenciados": diligenciados,
            })

        con_archivo = sum(1 for i in items if i["estado"] == EstadoDocumento.CARGADO)
        aplicables = [i for i in items if i["estado"] != EstadoDocumento.NO_APLICA]
        salida.append({
            "proceso": codigo_proceso,
            "etiqueta": ETIQUETAS_PROCESO[codigo_proceso],
            "items": items,
            "total_items": len(items),
            "items_cargados": con_archivo,
            "avance_pct": round(100 * con_archivo / len(aplicables)) if aplicables else 0,
        })

    return {
        "proyecto_id": proyecto_id,
        "nombre_comercial": proyecto.nombre_comercial,
        "codigo_cnd": getattr(proyecto, "codigo_cnd", None),
        "procesos": salida,
        "parametros_diligenciados": len(llenos),
        "parametros_totales": sum(
            len(_instancias(d)) for d in DEFINICIONES.values()),
    }
