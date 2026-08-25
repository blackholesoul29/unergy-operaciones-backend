"""_excels_cliente_por_proyecto (app/api/v1/reporte_cgm.py) -- punto 11 del
diagnostico de integridad de Fronteras, 2026-08-25.

Agrupaba fronteras por proyecto_id sin verificar que `f.proyecto` (la
relacion) realmente resolviera -- un proyecto_id huerfano (o cualquier caso
donde Frontera.proyecto no filtra deleted_at del lado de Proyecto, ver punto
18) revienta con AttributeError en `.proyecto.nombre_comercial` y tumba el
envio COMPLETO del reporte CGM para ese cliente, no solo esa fila. La funcion
vecina _datos_proyectos_para_resumen ya tenia el guard correcto (linea 99);
este mismo guard faltaba aca."""
import types

from app.api.v1 import reporte_cgm as mod
from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto


def test_frontera_con_proyecto_huerfano_no_revienta_el_envio(monkeypatch):
    # Frontera transient (sin agregar a una sesion) -- proyecto_id apunta a
    # algo, pero la relacion .proyecto nunca se cargo, asi que por defecto
    # es None. Exactamente el caso huerfano que preocupa.
    huerfana = Frontera(id=1, proyecto_id=999, codigo_frontera="frt00001",
                         nombre_frontera="Huerfana", tipo_frontera="generacion")

    proyecto_sano = Proyecto(id=1, nombre_comercial="Planta Sana")
    sana = Frontera(id=2, proyecto_id=1, codigo_frontera="frt00002",
                     nombre_frontera="Sana", tipo_frontera="generacion")
    sana.proyecto = proyecto_sano

    monkeypatch.setattr(mod, "_datos_proyectos_para_resumen", lambda db, gaia, fronteras: {})
    monkeypatch.setattr(mod.svc, "calcular_resumen_diario", lambda *a, **kw: [])
    monkeypatch.setattr(mod.svc, "calcular_resumen_mensual", lambda *a, **kw: [])
    monkeypatch.setattr(mod.svc, "generar_excel_cliente", lambda *a, **kw: b"excel-bytes")
    monkeypatch.setattr(mod.svc, "nombre_mes", lambda fecha: "agosto")

    adjuntos = mod._excels_cliente_por_proyecto(
        db=None, gaia=None, fronteras=[huerfana, sana], filas_por_frt={},
        dias=["2026-08-25"], dias_mes=["2026-08-25"], es_ultimo_dia_mes=False,
        fecha_inicio=types.SimpleNamespace(year=2026), fecha_archivo="2026-08-25",
    )

    # Solo la sana genera adjunto -- la huerfana se excluye en silencio en vez
    # de tumbar el envio completo.
    assert len(adjuntos) == 1
    assert "Planta_Sana" in adjuntos[0][1] or "planta_sana" in adjuntos[0][1]
