"""titulo_falla() (app.services.fallas.titulo) -- reemplaza a tipo_libre
(eliminado 2026-09-02): arma el título de una falla al vuelo desde
`clasificacion` en vez de leer un valor guardado. Espejo en Python de
tituloFalla() en el frontend (fallaTitulo.ts)."""
import types

from app.services.fallas.titulo import titulo_falla


def _falla(clasificacion=None, tipo_etiqueta=None):
    tipo = types.SimpleNamespace(etiqueta=tipo_etiqueta) if tipo_etiqueta else None
    return types.SimpleNamespace(clasificacion=clasificacion, tipo=tipo)


def test_categoria_opcion_con_subtipo():
    f = _falla(clasificacion={
        "categoria": "red", "categoria_etiqueta": "Red",
        "subtipo": "alta_tension", "subtipo_etiqueta": "Alta tensión",
    })
    assert titulo_falla(f) == "Alta tensión"


def test_categoria_opcion_con_subtipo_y_detalle():
    f = _falla(clasificacion={
        "categoria": "red", "categoria_etiqueta": "Red",
        "subtipo": "mantenimiento_red", "subtipo_etiqueta": "Mantenimiento de red",
        "detalle": "Cambio de poste",
    })
    assert titulo_falla(f) == "Mantenimiento de red: Cambio de poste"


def test_categoria_sin_subtipo_cae_a_etiqueta_de_categoria():
    f = _falla(clasificacion={"categoria": "frontera", "categoria_etiqueta": "Frontera"})
    assert titulo_falla(f) == "Frontera"


def test_inversores_con_varios_inversores_y_tipos():
    f = _falla(clasificacion={
        "categoria": "inversores", "categoria_etiqueta": "Inversores",
        "inversores": [
            {"nombre": "Inv1", "tipos_etiquetas": ["Sobre temperatura"]},
            {"nombre": "Inv2", "tipos_etiquetas": ["Falla del dispositivo"]},
        ],
    })
    titulo = titulo_falla(f)
    assert titulo.startswith("Inv1, Inv2 — ")
    assert "Sobre temperatura" in titulo and "Falla del dispositivo" in titulo


def test_inversores_sin_nombre_usa_id_de_proyecto_inversor():
    f = _falla(clasificacion={
        "categoria": "inversores", "categoria_etiqueta": "Inversores",
        "inversores": [{"nombre": None, "proyecto_inversor_id": 42, "tipos_etiquetas": []}],
    })
    assert titulo_falla(f) == "Inversor 42"


def test_falla_legacy_sin_clasificacion_cae_a_tipo_etiqueta():
    f = _falla(clasificacion=None, tipo_etiqueta="Falla de inversor")
    assert titulo_falla(f) == "Falla de inversor"


def test_falla_legacy_sin_clasificacion_ni_tipo():
    f = _falla(clasificacion=None, tipo_etiqueta=None)
    assert titulo_falla(f) == "Sin tipo"
