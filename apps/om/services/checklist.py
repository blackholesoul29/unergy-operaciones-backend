"""Los cuatro semáforos del checklist de comisionamiento y los KPIs del informe.

Cálculo puro sobre los JSONB de `proyecto_informe_om`: sin ORM y sin HTTP.

**Ninguno de los cuatro se edita directo.** Cada uno se deriva de sus ítems, y
la regla es siempre la misma: aprobar exige que TODO lo suyo esté aprobado Y que
haya evidencia subida donde corresponda. Un semáforo que se pudiera poner en
verde a mano no diría nada.

Solo estas cuatro categorías: el resto del catálogo viejo (CCTV, cableado,
transformadores, tableros, shelter, obras civiles, paneles, trackers, checklist
detallado por inversor) no se revive — ver el docstring de `ProyectoInformeOm`.
"""

TOTAL_CHECKLIST = 4

CLAVES_METEO = (
    "instalacion", "en_plataforma", "reporta_datos",
    "poa", "temperatura_ambiente", "velocidad_viento", "direccion_viento",
)

APROBADO = "aprobado"
PENDIENTE = "pendiente"


def _estado(item: dict | None) -> str | None:
    return (item or {}).get("estado")


def _con_evidencia(item: dict | None) -> bool:
    return bool((item or {}).get("evidencia"))


def fusion_solar(checklist: dict | None) -> str:
    """Aprueba si Starlink está aprobado, los datos se reportan coherentes,
    ningún inversor quedó marcado como limitado, y hay evidencia."""
    checklist = checklist or {}
    algun_limitado = any(
        (inv or {}).get("limitado") for inv in (checklist.get("inversores") or [])
    )
    ok = (
        _estado(checklist.get("starlink")) == APROBADO
        and _estado(checklist.get("datos_coherentes")) == APROBADO
        and not algun_limitado
        and _con_evidencia(checklist)
    )
    return APROBADO if ok else PENDIENTE


def frontera(checklist: dict | None) -> str:
    """Aprueba solo si el medidor principal Y el de respaldo están aprobados,
    cada uno con SU propia evidencia."""
    checklist = checklist or {}

    def medidor_ok(clave: str) -> bool:
        item = checklist.get(clave) or {}
        return item.get("estado") == APROBADO and _con_evidencia(item)

    ok = medidor_ok("principal") and medidor_ok("respaldo")
    return APROBADO if ok else PENDIENTE


def estacion_meteo(checklist: dict | None) -> str:
    """Aprueba si los siete ítems están aprobados; «reporta datos» además
    necesita su propia evidencia."""
    checklist = checklist or {}
    reporta = checklist.get("reporta_datos") or {}
    if reporta.get("estado") == APROBADO and not _con_evidencia(reporta):
        return PENDIENTE
    todos = all(_estado(checklist.get(k)) == APROBADO for k in CLAVES_METEO)
    return APROBADO if todos else PENDIENTE


def reconectador(checklist: dict | None) -> str:
    """Sin reconectador queda SIEMPRE pendiente.

    No es un descuido: «no tiene» no es lo mismo que «está bien», y dejarlo en
    verde escondería una planta cuyo reconectador nadie registró.
    """
    checklist = checklist or {}
    if not checklist.get("tiene"):
        return PENDIENTE
    ok = (
        _estado(checklist.get("en_plataforma")) == APROBADO
        and _estado(checklist.get("calidad_datos")) == APROBADO
        and _con_evidencia(checklist)
    )
    return APROBADO if ok else PENDIENTE


def semaforos(ficha) -> dict[str, str]:
    """Los cuatro estados de una ficha (o de `None`, si no existe todavía)."""
    return {
        "fusion_solar_estado": fusion_solar(
            getattr(ficha, "checklist_fusion_solar", None)
        ),
        "frontera_estado": frontera(getattr(ficha, "checklist_frontera", None)),
        "estacion_meteo_estado": estacion_meteo(
            getattr(ficha, "checklist_estacion_meteo", None)
        ),
        "reconectador_estado": reconectador(
            getattr(ficha, "checklist_reconectador", None)
        ),
    }


def kpis(ficha) -> dict:
    """Conteos de pruebas, eventos y checklist, más el estado global."""
    pruebas = (getattr(ficha, "protocolo_pruebas", None) or []) if ficha else []
    eventos = (getattr(ficha, "eventos_operativos", None) or []) if ficha else []

    no_conformes = sum(
        1 for p in pruebas if (p or {}).get("resultado") == "no_conforme"
    )
    en_gestion = sum(1 for e in eventos if (e or {}).get("estado") == "en_gestion")
    sin_cerrar = sum(
        1 for e in eventos if (e or {}).get("estado") in ("abierta", "en_gestion")
    )
    aprobados = sum(
        1 for estado in semaforos(ficha).values() if estado == APROBADO
    )

    return {
        "pruebas_ejecutadas": len(pruebas),
        "pruebas_conformes": sum(
            1 for p in pruebas if (p or {}).get("resultado") == "conforme"
        ),
        "pruebas_no_conformes": no_conformes,
        "eventos_total": len(eventos),
        "eventos_cerrados": sum(
            1 for e in eventos if (e or {}).get("estado") == "cerrada"
        ),
        "eventos_en_gestion": en_gestion,
        "checklist_aprobados": aprobados,
        "checklist_total": TOTAL_CHECKLIST,
        # Basta UNA prueba no conforme o UN evento sin cerrar para que el
        # proyecto pida atención, sin importar cuántos semáforos estén verdes.
        "estado_global": (
            "atencion" if (no_conformes > 0 or sin_cerrar > 0) else "operativo"
        ),
    }
