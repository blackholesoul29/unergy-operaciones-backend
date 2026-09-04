"""Cliente y persistencia del proxy EVO (DailySpot + Clima).

EVO es un servicio interno al que se llega por Tailscale. Este backend le hace
de proxy autenticado y, además, GUARDA lo que pasa: las series de precio de
bolsa y los índices climáticos quedan en la base para poder consultarlas sin
depender de que EVO esté arriba.

`ponytail: SQL crudo, no seis modelos de Django`. Las seis tablas
(`precios_bolsa_diario`, `precios_bolsa_horario`, `clima_forecasts`,
`clima_oni_monthly`, `clima_price_monthly`, `clima_precip_monthly`) están entre
las que nunca tuvieron modelo SQLAlchemy (ver apps/README.md) y solo las toca
este módulo, siempre con `INSERT … ON CONFLICT DO UPDATE`. Reproducir ese upsert
con el ORM exige `bulk_create(update_conflicts=…)` y una lista de campos por
tabla: más código para la misma sentencia. Si algún otro recurso empieza a
leerlas, ahí sí valen los modelos.
"""

import json
import logging
import os
import threading

import httpx
from django.db import close_old_connections, connection

logger = logging.getLogger("operaciones.evo")

TIMEOUT = httpx.Timeout(10.0, read=30.0)


class EvoNoConfigurado(RuntimeError):
    pass


class EvoInalcanzable(RuntimeError):
    pass


class EvoTimeout(RuntimeError):
    pass


class EvoRespondioError(RuntimeError):
    def __init__(self, status_code: int, texto: str):
        super().__init__(texto)
        self.status_code = status_code
        self.texto = texto


def get(ruta: str, params: dict | None = None) -> dict:
    """GET contra EVO. Traduce cada fallo de red a su propia excepción."""
    base = os.environ.get("EVO_API_URL", "")
    if not base:
        raise EvoNoConfigurado("EVO_API_URL not configured")

    cabeceras = {}
    token = os.environ.get("EVO_API_TOKEN", "")
    if token:
        cabeceras["X-EVO-Token"] = token

    url = f'{base.rstrip("/")}/{ruta.lstrip("/")}'
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            respuesta = http.get(url, headers=cabeceras, params=params)
            respuesta.raise_for_status()
            return respuesta.json()
    except httpx.ConnectError as exc:
        raise EvoInalcanzable("EVO unreachable") from exc
    except httpx.TimeoutException as exc:
        raise EvoTimeout("EVO timeout") from exc
    except httpx.HTTPStatusError as exc:
        raise EvoRespondioError(exc.response.status_code, exc.response.text) from exc


def consultar(sql: str, params: dict) -> list[dict]:
    """Ejecuta un SELECT y devuelve dicts con los nombres de columna."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columnas = [c[0] for c in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def en_segundo_plano(funcion, *args) -> None:
    """Lanza `funcion` en un hilo, cerrando la conexión al terminar.

    Un hilo de Django que toca la base NO pasa por el ciclo de request, que es
    quien normalmente cierra la conexión: sin `close_old_connections` cada
    llamada deja una conexión abierta hasta agotar el pool. Ese es el mismo
    motivo de los hooks de Celery en `config/celery.py`.
    """
    def envoltura():
        try:
            funcion(*args)
        finally:
            close_old_connections()

    threading.Thread(target=envoltura, daemon=True).start()


# ---------------------------------------------------------------------------
# Persistencia — «lo mejor que se pueda»: si falla, se loguea y se sigue
# ---------------------------------------------------------------------------

_SQL_BOLSA_DIARIO = """
    INSERT INTO precios_bolsa_diario
        (fecha, precio_promedio, precio_min, precio_max, precio_escasez,
         demanda_gwh, hidro_pct, termica_pct, renovable_pct, menor_pct,
         hora_pico, spread, source_data)
    VALUES (%(fecha)s, %(avg)s, %(min)s, %(max)s, %(escasez)s,
            %(demanda)s, %(hidro)s, %(termica)s, %(renovable)s, %(menor)s,
            %(pico)s, %(spread)s, %(source)s)
    ON CONFLICT (fecha) DO UPDATE SET
        precio_promedio = EXCLUDED.precio_promedio,
        precio_min = EXCLUDED.precio_min,
        precio_max = EXCLUDED.precio_max,
        precio_escasez = EXCLUDED.precio_escasez,
        demanda_gwh = EXCLUDED.demanda_gwh,
        hidro_pct = EXCLUDED.hidro_pct,
        termica_pct = EXCLUDED.termica_pct,
        renovable_pct = EXCLUDED.renovable_pct,
        menor_pct = EXCLUDED.menor_pct,
        hora_pico = EXCLUDED.hora_pico,
        spread = EXCLUDED.spread,
        source_data = EXCLUDED.source_data
"""

_SQL_BOLSA_HORARIO = """
    INSERT INTO precios_bolsa_horario
        (fecha, hora, precio_cop_kwh, gen_hidro, gen_termica,
         gen_renovable, gen_menor, planta_marginal)
    VALUES (%(fecha)s, %(hora)s, %(precio)s, %(hidro)s, %(termica)s,
            %(renovable)s, %(menor)s, %(marginal)s)
    ON CONFLICT (fecha, hora) DO UPDATE SET
        precio_cop_kwh = EXCLUDED.precio_cop_kwh,
        gen_hidro = EXCLUDED.gen_hidro,
        gen_termica = EXCLUDED.gen_termica,
        gen_renovable = EXCLUDED.gen_renovable,
        gen_menor = EXCLUDED.gen_menor,
        planta_marginal = EXCLUDED.planta_marginal
"""


def guardar_dailyspot(datos: dict) -> None:
    """Guarda el DailySpot del día y sus 24 horas. No levanta nunca."""
    fecha = datos.get("date")
    if not fecha:
        return
    resumen = datos.get("summary", {})
    precios = datos.get("prices", {})
    generacion = datos.get("generation", {})
    marginales = datos.get("marginal_plants", {})

    try:
        with connection.cursor() as cursor:
            cursor.execute(_SQL_BOLSA_DIARIO, {
                "fecha": fecha,
                "avg": resumen.get("price_avg"),
                "min": resumen.get("price_min"),
                "max": resumen.get("price_max"),
                "escasez": datos.get("scarcity_price"),
                "demanda": resumen.get("total_gwh"),
                "hidro": resumen.get("hydro_pct"),
                "termica": resumen.get("thermal_pct"),
                "renovable": resumen.get("renewable_pct"),
                "menor": resumen.get("minor_pct"),
                "pico": resumen.get("peak_hour"),
                "spread": resumen.get("spread"),
                "source": json.dumps({"fetched_at": datos.get("fetched_at")}),
            })
            for hora_txt, precio in precios.items():
                gen = generacion.get(hora_txt, {})
                cursor.execute(_SQL_BOLSA_HORARIO, {
                    "fecha": fecha, "hora": int(hora_txt), "precio": precio,
                    "hidro": gen.get("Hidraulica"),
                    "termica": gen.get("Termica"),
                    "renovable": gen.get("Renovables"),
                    "menor": gen.get("Menores"),
                    "marginal": marginales.get(hora_txt),
                })
        logger.info("DailySpot guardado para %s (%d horas)", fecha, len(precios))
    except Exception:
        logger.exception("no se pudo guardar el DailySpot")


def guardar_forecast(datos: dict) -> None:
    """Guarda el pronóstico climático del día. No levanta nunca."""
    if not datos.get("models_available"):
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO clima_forecasts
                    (forecast_date, forecast_json, model_version)
                VALUES (CURRENT_DATE, %(datos)s, %(version)s)
                ON CONFLICT DO NOTHING
                """,
                {
                    "datos": json.dumps(datos, default=str),
                    "version": datos.get("source", "unknown"),
                },
            )
    except Exception:
        logger.exception("no se pudo guardar el pronóstico climático")
