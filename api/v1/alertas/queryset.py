"""Las tres alertas operativas: persistidas, huérfanos/duplicados y déficit PPA.

Las tres viven juntas porque comparten la pantalla, pero son de naturalezas
distintas y conviene no confundirlas:

- **`/ppa-vencimiento`** lee la tabla `alertas`, que escribe el job de
  vencimientos. Es la única con persistencia.
- **`/contratos-ppa`** y **`/cumplimiento-ppa`** se calculan al vuelo en cada
  petición y no tienen tabla propia.

La vigencia GESCON la resuelve `apps/mercado_xm/services/gescon_vigencia.py`, el
mismo núcleo que usan Cumplimiento y `GET /asic`. Una fila es la versión vigente
de su SIC solo si ningún relevo o modificación posterior la superó, procesando
por `fecha_inicio` (cuándo tomó efecto) y NO por `fecha_solicitud` (cuándo se
radicó): ordenar por radicación era el bug histórico que hacía aparecer una
planta reubicada como «activa en dos contratos a la vez».
"""

from collections import defaultdict
from datetime import date

from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services.gescon_vigencia import resolver_vigencias
from apps.proyectos import models as py_models


def alertas_persistidas(estado: str | None = None):
    from apps.monitoreo import models as mo_models

    consulta = mo_models.Alerta.objects.order_by("-trigger_date", "-id")
    if estado is not None:
        consulta = consulta.filter(status=estado)
    return consulta


# ---------------------------------------------------------------------------
# Huérfanos y duplicados de contratos ASIC
# ---------------------------------------------------------------------------

def _publicadas_ordenadas():
    """Universo de solicitudes publicadas, en el orden que exige la vigencia.

    El orden es `fecha_inicio`, luego `fecha_solicitud`, luego `created_at`, con
    los nulos primero: es el que espera `resolver_vigencias`.
    """
    return list(
        mx_models.AsicSolicitud.objects
        .filter(estado_solicitud="publicado", codigo_sic_contrato__isnull=False)
        .exclude(tipo_solicitud="desistimiento")
        .order_by("fecha_inicio", "fecha_solicitud", "created_at")
    )


def build_contratos_ppa(hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    registros = _publicadas_ordenadas()

    # `hasta=hoy`: un relevo con efecto FUTURO todavía no desplaza a la versión
    # vigente de hoy. La pregunta de este endpoint es «qué está activo HOY».
    vigencias = resolver_vigencias(registros, hasta=hoy)

    sics_por_proyecto: dict[int, list[dict]] = defaultdict(list)
    for registro in registros:
        vigencia = vigencias[registro.id]
        if not vigencia.vigente or registro.tipo_solicitud == "terminacion":
            continue
        fin = vigencia.fecha_fin_efectiva
        # `None` (ventana abierta) se excluye por paridad con el comportamiento
        # anterior, no porque no tenga sentido incluirla.
        if fin is None or fin < hoy or not registro.proyecto_id:
            continue
        sics_por_proyecto[registro.proyecto_id].append({
            "id": registro.id,
            "codigo_sic_contrato": registro.codigo_sic_contrato,
            "contrato_interno": registro.contrato_interno,
            "tipo_solicitud": registro.tipo_solicitud,
            "fecha_inicio": registro.fecha_inicio,
            # Ventana EFECTIVA: es la que define la simultaneidad real.
            "fecha_fin": fin,
            "porcentaje_fncer": registro.porcentaje_fncer,
            "es_duplicado": bool(registro.es_duplicado),
        })

    proyectos = list(
        py_models.Proyecto.objects
        # `tipo_proyecto` es nullable y el `!=` de SQL descarta los NULL, pero
        # el `exclude()` de Django los CONSERVA (al negar añade un `IS NOT
        # NULL`). Sin el segundo exclude, los proyectos sin tipo aparecían como
        # huérfanos y no lo son.
        .exclude(estado="cancelado")
        .exclude(tipo_proyecto="autoconsumo")
        .exclude(tipo_proyecto__isnull=True)
        .order_by("nombre_comercial")
        .values("id", "nombre_comercial", "tipo_proyecto", "estado")
    )
    con_sic = set(sics_por_proyecto)

    huerfanos = [
        {
            "proyecto_id": p["id"],
            "nombre_comercial": p["nombre_comercial"],
            "tipo_proyecto": p["tipo_proyecto"],
            "estado": p["estado"],
        }
        for p in proyectos if p["id"] not in con_sic
    ]

    return {
        "fecha_consulta": str(hoy),
        "huerfanos": huerfanos,
        "duplicados": _duplicados(sics_por_proyecto, {p["id"]: p for p in proyectos}),
    }


def _duplicados(sics_por_proyecto: dict, indice: dict) -> list[dict]:
    """Proyectos con dos o más contratos activos a la vez, sin resolver.

    Los marcados `es_duplicado` (compra en bolsa) ya declararon su cruce y no
    deben volver a alertar.
    """
    salida = []
    for proyecto_id, sics in sics_por_proyecto.items():
        sin_resolver = [s for s in sics if not s["es_duplicado"]]
        if len(sin_resolver) < 2:
            continue
        proyecto = indice.get(proyecto_id)
        if not proyecto:
            continue
        salida.append({
            "proyecto_id": proyecto_id,
            "nombre_comercial": proyecto["nombre_comercial"],
            "tipo_proyecto": proyecto["tipo_proyecto"],
            "sics": sorted(
                [
                    {
                        "id": s["id"],
                        "codigo_sic_contrato": s["codigo_sic_contrato"],
                        "contrato_interno": s["contrato_interno"],
                        "tipo_solicitud": s["tipo_solicitud"],
                        "fecha_inicio": str(s["fecha_inicio"]) if s["fecha_inicio"] else None,
                        "fecha_fin": str(s["fecha_fin"]) if s["fecha_fin"] else None,
                        "porcentaje_fncer": (
                            float(s["porcentaje_fncer"])
                            if s["porcentaje_fncer"] else None
                        ),
                    }
                    for s in sin_resolver
                ],
                key=lambda s: s["fecha_inicio"] or "",
            ),
        })
    # Primero los peores: más contratos simultáneos = más urgente.
    salida.sort(key=lambda d: len(d["sics"]), reverse=True)
    return salida


# ---------------------------------------------------------------------------
# Déficit de cumplimiento PPA
# ---------------------------------------------------------------------------

def build_cumplimiento_ppa(anio: int, mes: int, umbral_pct: float) -> dict:
    """Una alerta por contrato cuya generación real no llega al umbral."""
    filas = (
        mx_models.CumplimientoMensual.objects
        .filter(anio=anio, mes=mes, contrato_ppa__isnull=False)
        .select_related("contrato_ppa")
    )

    alertas = []
    for fila in filas:
        generado = float(fila.gen_total_mwh) if fila.gen_total_mwh is not None else 0
        comprometido = (
            float(fila.compromiso_mwh) if fila.compromiso_mwh is not None else None
        )
        if not comprometido or comprometido <= 0:
            continue

        cobertura = (generado / comprometido) * 100
        if cobertura >= umbral_pct:
            continue

        deficit = round(comprometido - generado, 3)
        precio = (
            float(fila.precio_bolsa_promedio)
            if fila.precio_bolsa_promedio is not None else None
        )
        # El déficit hay que cubrirlo comprando en bolsa: MWh -> kWh por el precio.
        impacto = round(deficit * 1000 * precio, 0) if precio is not None else None

        contrato = fila.contrato_ppa
        nombre = contrato.nombre_interno if contrato else None
        alertas.append({
            "tipo": "deficit_cumplimiento_ppa",
            "severidad": "alta" if cobertura < 80 else "media",
            "contrato_ppa_id": fila.contrato_ppa_id,
            "contrato_nombre": nombre,
            "comprador_nombre": contrato.comprador_nombre if contrato else None,
            "anio": anio,
            "mes": mes,
            "gen_total_mwh": generado,
            "compromiso_mwh": comprometido,
            "cobertura_pct": round(cobertura, 1),
            "deficit_mwh": deficit,
            "impacto_estimado_cop": impacto,
            "precio_bolsa_promedio": precio,
            "mensaje": (
                f"{nombre or 'Contrato'}: déficit de {deficit:.1f} MWh "
                f"({cobertura:.0f}% cobertura)"
                + (f", impacto estimado ${impacto:,.0f} COP" if impacto else "")
            ),
        })

    alertas.sort(key=lambda a: a["cobertura_pct"])
    return {
        "fecha_consulta": str(date.today()),
        "periodo": {"anio": anio, "mes": mes},
        "umbral_pct": umbral_pct,
        "total_alertas": len(alertas),
        "alertas": alertas,
    }
