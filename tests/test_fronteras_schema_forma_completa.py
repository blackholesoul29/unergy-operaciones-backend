"""FronteraOut -- fija la forma completa del schema (punto 14 del
diagnostico de integridad de Fronteras, 2026-08-25).

Sin esto, un campo eliminado a proposito (ej. los ~25 campos de GESCON sin
uso que se sacaron en varias rondas esta sesion) podria "resucitar" por
accidente sin que ningun test lo note, o un campo que si se usa podria
desaparecer sin que nada avise. La lista se congela aca; si el conjunto de
campos cambia a proposito, este test se actualiza junto con el cambio."""
from app.schemas.fronteras import FronteraOut

_CAMPOS_ESPERADOS = {
    "agente_exportador", "agente_importador", "altitud_msnm",
    "capacidad_efectiva_mw", "capacidad_transporte_mw", "centro_poblado",
    "clase_ct", "clase_medidor", "clase_pt",
    "clasificacion_industrial_especifica", "clasificacion_industrial_general",
    "clasificacion_recurso", "clientes_cgm", "codigo_ciiu", "codigo_frontera",
    "codigo_sic_frontera_generacion",
    "codigo_sic_frontera_usuario", "codigo_sic_submercado_consumo",
    "codigo_sic_submercado_exportador", "created_at", "departamento",
    "direccion", "entidad_calibradora_med_ppal", "entidad_calibradora_med_resp",
    "es_agrupadora", "es_principal_embebido", "estado", "factor_acordado",
    "factor_ajuste", "factor_perdidas", "factor_perdidas_frontera_principal",
    "factor_psf", "fecha_actualizacion_ppal", "fecha_actualizacion_resp",
    "fecha_calibracion_med_ppal", "fecha_calibracion_med_resp",
    "fecha_cambio_med_ppal", "fecha_cambio_med_resp",
    "fecha_inicio_representacion",
    "fecha_registro_asic", "fecha_ultima_generacion", "generando_actual",
    "id", "latitud", "longitud", "marca_med_ppal", "marca_med_resp",
    "modelo_med_ppal", "modelo_med_resp", "municipio",
    "nivel_tension", "nivel_tension_kv", "nombre_frontera",
    "nombre_recurso_generacion", "nro_serie_med_ppal", "nro_serie_med_resp",
    "num_elementos_med_ppal", "num_elementos_med_resp", "operador_comercial",
    "operador_correos", "operador_red_id", "potencia_maxima_declarada",
    "proyecto_fecha_inicio_comercializacion", "proyecto_id", "proyecto_nombre",
    "quoia_border_id", "registrada_por",
    "representante_anterior", "representante_frontera",
    "tipo_frontera", "tipo_punto_medicion", "tipo_tecnologia",
    "transferencia_maxima_kwh", "updated_at",
}


def test_fronteraout_no_gana_ni_pierde_campos_sin_querer():
    actuales = set(FronteraOut.model_fields.keys())
    de_mas = actuales - _CAMPOS_ESPERADOS
    de_menos = _CAMPOS_ESPERADOS - actuales
    assert not de_mas, f"Campos nuevos no esperados en FronteraOut: {sorted(de_mas)}"
    assert not de_menos, f"Campos esperados que ya no estan en FronteraOut: {sorted(de_menos)}"


def test_fronteraout_no_expone_los_campos_de_agrupacion_eliminados():
    """agrupada_bajo_id/embebida_bajo_id/frontera_gemela_id se eliminaron por
    completo (migracion 080, 0/145 poblados, sin relationship real) -- si
    alguna vez "resucitan" por accidente (ej. un merge mal resuelto), este
    test lo atrapa explicitamente en vez de depender solo del set completo."""
    campos = set(FronteraOut.model_fields.keys())
    assert "agrupada_bajo_id" not in campos
    assert "embebida_bajo_id" not in campos
    assert "frontera_gemela_id" not in campos


def test_fronteraout_no_expone_los_campos_de_ficha_tecnica_eliminados():
    """tipo_extraccion_ppal/password_medidor_ppal/etc se eliminaron por
    completo (0/145 poblados, sin fuente real ni en Quoia ni manual)."""
    campos = set(FronteraOut.model_fields.keys())
    for sufijo in ("ppal", "resp"):
        assert f"tipo_extraccion_{sufijo}" not in campos
        assert f"password_medidor_{sufijo}" not in campos
        assert f"ip_modem_{sufijo}" not in campos
        assert f"puerto_modem_{sufijo}" not in campos
        assert f"canal_comunicacion_{sufijo}" not in campos
