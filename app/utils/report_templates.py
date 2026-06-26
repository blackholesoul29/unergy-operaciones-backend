"""
Plantillas HTML (Jinja2) y utilidades de datos para gráficos de los informes
generados automáticamente por :mod:`app.services.report_generator`.

El HTML producido aquí es un *borrador*: se guarda en ``informes_guardados`` con
estado ``borrador`` y luego el equipo lo edita/aprueba desde el flujo editorial
existente (ver ``app/api/v1/informes.py``). Por eso las plantillas usan las mismas
clases CSS que el frontend ya conoce (``rpt-page``) para que la previsualización y
el editor del portafolio funcionen sin cambios.

``charts_data`` se entrega en un formato compatible con Chart.js
(``{labels: [...], datasets: [...]}``), que es lo que consume el frontend de
monitoreo para renderizar las gráficas.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from jinja2 import Environment, select_autoescape

# Entorno Jinja2 con autoescape activo (los nombres de proyecto/cliente provienen
# de la BD; autoescape evita romper el HTML o inyectar marcado accidentalmente).
_env = Environment(autoescape=select_autoescape(default_for_string=True))


# ── Bloques reutilizables ────────────────────────────────────────────────────

# Tarjetas KPI: una fila de tarjetas con etiqueta + valor + unidad opcional.
_KPI_CARDS = """
<div class="rpt-kpi-grid" style="display:flex;flex-wrap:wrap;gap:12px;margin:16px 0;">
  {% for kpi in kpis %}
  <div class="rpt-kpi-card" style="flex:1 1 160px;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;">
    <div class="rpt-kpi-label" style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">{{ kpi.label }}</div>
    <div class="rpt-kpi-value" style="font-size:24px;font-weight:700;color:#0f172a;">
      {{ kpi.value }}{% if kpi.unit %}<span style="font-size:13px;font-weight:500;color:#64748b;"> {{ kpi.unit }}</span>{% endif %}
    </div>
  </div>
  {% endfor %}
</div>
"""

# Tabla genérica: encabezados + filas.
_DATA_TABLE = """
<table class="rpt-table" style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px;">
  <thead>
    <tr>
      {% for h in headers %}<th style="text-align:left;border-bottom:2px solid #cbd5e1;padding:6px 8px;color:#334155;">{{ h }}</th>{% endfor %}
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    <tr>
      {% for cell in row %}<td style="border-bottom:1px solid #e2e8f0;padding:6px 8px;">{{ cell }}</td>{% endfor %}
    </tr>
    {% endfor %}
    {% if not rows %}
    <tr><td colspan="{{ headers|length }}" style="padding:10px;color:#94a3b8;text-align:center;">Sin datos para el período.</td></tr>
    {% endif %}
  </tbody>
</table>
"""

# Página base de un informe (un proyecto o la consolidada del portafolio).
# Marcamos ``rpt-page`` para que encaje en el editor/compositor existente.
_BASE_PAGE = """
<div class="rpt-page">
  <header class="rpt-header" style="border-bottom:3px solid #0ea5e9;padding-bottom:8px;margin-bottom:8px;">
    <h1 style="margin:0;font-size:22px;color:#0f172a;">{{ titulo }}</h1>
    <p style="margin:4px 0 0;color:#475569;font-size:14px;">{{ subtitulo }}</p>
    <p style="margin:2px 0 0;color:#64748b;font-size:12px;">Período: {{ periodo_display }}</p>
  </header>

  {% if alerta %}
  <div class="rpt-alert" style="background:#fef2f2;border:1px solid #fecaca;color:#991b1b;border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px;">
    ⚠ {{ alerta }}
  </div>
  {% endif %}

  {{ kpi_cards }}

  {% if secciones %}
    {% for sec in secciones %}
    <section style="margin-top:16px;">
      <h2 style="font-size:16px;color:#0f172a;border-bottom:1px solid #e2e8f0;padding-bottom:4px;">{{ sec.titulo }}</h2>
      {% if sec.descripcion %}<p style="color:#475569;font-size:13px;">{{ sec.descripcion }}</p>{% endif %}
      {{ sec.tabla }}
    </section>
    {% endfor %}
  {% endif %}

  <footer class="rpt-footer" style="margin-top:24px;color:#94a3b8;font-size:11px;border-top:1px solid #e2e8f0;padding-top:6px;">
    Borrador generado automáticamente — requiere revisión y aprobación antes de su envío.
  </footer>
</div>
"""

_kpi_tpl = _env.from_string(_KPI_CARDS)
_table_tpl = _env.from_string(_DATA_TABLE)
_page_tpl = _env.from_string(_BASE_PAGE)


# ── API pública ──────────────────────────────────────────────────────────────

def render_kpi_cards(kpis: Iterable[Mapping[str, Any]]) -> str:
    """Renderiza una fila de tarjetas KPI. Cada kpi: ``{label, value, unit?}``."""
    return _kpi_tpl.render(kpis=list(kpis or []))


def render_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Renderiza una tabla simple (encabezados + filas)."""
    return _table_tpl.render(headers=list(headers or []), rows=[list(r) for r in (rows or [])])


def render_report(report_type: str, context: Mapping[str, Any]) -> str:
    """Renderiza el HTML de un informe.

    ``context`` admite:
      - ``titulo`` (str), ``subtitulo`` (str), ``periodo_display`` (str)
      - ``kpis`` (lista de dicts ``{label, value, unit?}``)
      - ``secciones`` (lista de dicts ``{titulo, descripcion?, headers, rows}``)
      - ``alerta`` (str opcional): banner de advertencia (p. ej. huecos de datos)

    ``report_type`` ('op' | 'fmo' | 'port') sólo afecta el subtítulo por defecto;
    la estructura es común para que el editor las trate igual.
    """
    secciones_in = context.get("secciones") or []
    secciones = [
        {
            "titulo": s.get("titulo", ""),
            "descripcion": s.get("descripcion"),
            "tabla": render_table(s.get("headers", []), s.get("rows", [])),
        }
        for s in secciones_in
    ]
    default_sub = {
        "op": "Informe operativo de generación",
        "fmo": "Informe de operación y cumplimiento PPA",
        "port": "Informe consolidado de portafolio",
    }.get(report_type, "Informe")

    return _page_tpl.render(
        titulo=context.get("titulo", "Informe"),
        subtitulo=context.get("subtitulo", default_sub),
        periodo_display=context.get("periodo_display", ""),
        alerta=context.get("alerta"),
        kpi_cards=render_kpi_cards(context.get("kpis", [])),
        secciones=secciones,
    )


def generate_chart_data(
    labels: list[Any],
    datasets: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Formatea datos para Chart.js.

    Devuelve ``{"labels": [...], "datasets": [{"label", "data", ...}]}``.
    Cada dataset debe traer al menos ``label`` y ``data``; cualquier otra clave
    (``backgroundColor``, ``borderColor``, ``type``…) se preserva tal cual.

    Valida que cada serie tenga la misma longitud que ``labels`` para no producir
    gráficas desalineadas (errores silenciosos en el frontend).
    """
    labels = list(labels or [])
    out_datasets: list[dict[str, Any]] = []
    for ds in datasets or []:
        data = list(ds.get("data") or [])
        if len(data) != len(labels):
            raise ValueError(
                f"dataset '{ds.get('label', '?')}' tiene {len(data)} puntos "
                f"pero hay {len(labels)} labels"
            )
        out = {k: v for k, v in ds.items()}
        out["data"] = data
        out.setdefault("label", "")
        out_datasets.append(out)
    return {"labels": labels, "datasets": out_datasets}
