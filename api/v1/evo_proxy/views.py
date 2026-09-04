"""ViewSet del proxy EVO: DailySpot y Clima.

Todo lo que viene de EVO se devuelve tal cual, sin serializer: es un proxy y
reinterpretar su forma solo añadiría un sitio donde desincronizarse.
"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.logging import class_logger_wrapper, log_endpoint
from api.permissions import RolePermission
from apps.mercado_xm import models as mx_models
from apps.mercado_xm.services import evo


def _entero(request, nombre, defecto, minimo, maximo) -> int:
    crudo = request.query_params.get(nombre)
    if crudo in (None, ""):
        return defecto
    if not crudo.isdigit() or not minimo <= int(crudo) <= maximo:
        raise ValidationError({nombre: f"Entero entre {minimo} y {maximo}."})
    return int(crudo)


class _ProxyMixin:
    """Traduce los fallos de EVO a los mismos códigos que devuelve hoy."""

    def _evo(self, ruta, params=None):
        try:
            return Response(evo.get(ruta, params))
        except evo.EvoNoConfigurado as exc:
            return Response({"detail": str(exc)}, status=503)
        except evo.EvoInalcanzable as exc:
            return Response({"detail": str(exc)}, status=503)
        except evo.EvoTimeout as exc:
            return Response({"detail": str(exc)}, status=504)
        except evo.EvoRespondioError as exc:
            return Response({"detail": exc.texto}, status=exc.status_code)


@class_logger_wrapper(name="Operaciones | Mercado XM | EVO")
class EvoProxyViewSet(_ProxyMixin, viewsets.GenericViewSet):
    """Proxy a EVO (DailySpot + Clima) y el histórico que se guarda de paso.

    GET  /api/v1/evo/dailyspot/latest       proxy; persiste en segundo plano
    GET  /api/v1/evo/dailyspot/text         proxy puro
    GET  /api/v1/evo/dailyspot/history[?days=30]
    GET  /api/v1/evo/dailyspot/hourly/{fecha}
    GET  /api/v1/evo/clima/forecast         proxy; persiste en segundo plano
    GET  /api/v1/evo/clima/trading[?tariff=]
    GET  /api/v1/evo/clima/history[?limit=10]
    GET  /api/v1/evo/clima/forecast/{id}
    GET  /api/v1/evo/precios/historico[?desde=&hasta=&limit=365]
    GET  /api/v1/evo/clima/oni[?years=10]
    GET  /api/v1/evo/clima/prices[?years=26]
    GET  /api/v1/evo/clima/precip[?region=Andina&years=10]
    GET  /api/v1/evo/health
    POST /api/v1/evo/clima/bulk-load        solo admin

    **La persistencia es en segundo plano y «lo mejor que se pueda».** Se guarda
    en un hilo para no hacer esperar al cliente, y si el guardado falla se
    loguea sin afectar la respuesta: el dato ya se le entregó.
    """

    permission_classes = [RolePermission]
    pagination_class = None
    http_method_names = ["get", "post", "head", "options"]
    queryset = mx_models.PrecioBolsaMensual.objects.none()

    # ── DailySpot ─────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="dailyspot/latest")
    def dailyspot_latest(self, request):
        respuesta = self._evo("/dailyspot/latest")
        if respuesta.status_code == 200:
            evo.en_segundo_plano(evo.guardar_dailyspot, respuesta.data)
        return respuesta

    @action(detail=False, methods=["get"], url_path="dailyspot/text")
    def dailyspot_text(self, request):
        return self._evo("/dailyspot/text")

    @action(detail=False, methods=["get"], url_path="dailyspot/history")
    def dailyspot_history(self, request):
        dias = _entero(request, "days", 30, 1, 365)
        return Response(evo.consultar(
            """
            SELECT fecha, precio_promedio, precio_min, precio_max,
                   precio_escasez, demanda_gwh, hidro_pct, spread, hora_pico
            FROM precios_bolsa_diario
            ORDER BY fecha DESC LIMIT %(dias)s
            """,
            {"dias": dias},
        ))

    @action(
        detail=False, methods=["get"],
        url_path=r"dailyspot/hourly/(?P<fecha>[^/]+)",
    )
    def dailyspot_hourly(self, request, fecha=None):
        return Response(evo.consultar(
            """
            SELECT hora, precio_cop_kwh, gen_hidro, gen_termica,
                   gen_renovable, gen_menor, planta_marginal
            FROM precios_bolsa_horario
            WHERE fecha = %(fecha)s ORDER BY hora
            """,
            {"fecha": fecha},
        ))

    @action(detail=False, methods=["get"], url_path="precios/historico")
    def precios_historico(self, request):
        """Precios de bolsa históricos, con rango de fechas opcional."""
        limite = _entero(request, "limit", 365, 1, 3650)
        params: dict = {"limite": limite}
        condiciones = []
        for nombre, comparador in (("desde", ">="), ("hasta", "<=")):
            valor = request.query_params.get(nombre)
            if valor:
                condiciones.append(f"fecha {comparador} %({nombre})s")
                params[nombre] = valor
        where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

        return Response(evo.consultar(
            f"""
            SELECT fecha, precio_promedio, precio_min, precio_max,
                   precio_escasez, demanda_gwh, hidro_pct, termica_pct,
                   renovable_pct, menor_pct, hora_pico, spread
            FROM precios_bolsa_diario
            {where}
            ORDER BY fecha DESC LIMIT %(limite)s
            """,
            params,
        ))

    # ── Clima ─────────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="clima/forecast")
    def clima_forecast(self, request):
        respuesta = self._evo("/clima/forecast")
        if respuesta.status_code == 200:
            evo.en_segundo_plano(evo.guardar_forecast, respuesta.data)
        return respuesta

    @action(detail=False, methods=["get"], url_path="clima/trading")
    def clima_trading(self, request):
        tarifa = request.query_params.get("tariff")
        return self._evo(
            "/clima/trading", {"tariff": tarifa} if tarifa is not None else None
        )

    @action(detail=False, methods=["get"], url_path="clima/history")
    def clima_history(self, request):
        limite = _entero(request, "limit", 10, 1, 100)
        return Response(evo.consultar(
            """
            SELECT id, forecast_date, model_version, created_at
            FROM clima_forecasts
            ORDER BY forecast_date DESC LIMIT %(limite)s
            """,
            {"limite": limite},
        ))

    @action(
        detail=False, methods=["get"],
        url_path=r"clima/forecast/(?P<forecast_id>[0-9]+)",
    )
    def clima_forecast_detalle(self, request, forecast_id=None):
        filas = evo.consultar(
            """
            SELECT id, forecast_date, forecast_json, model_version, created_at
            FROM clima_forecasts WHERE id = %(fid)s
            """,
            {"fid": int(forecast_id)},
        )
        if not filas:
            raise NotFound("Forecast not found")
        return Response(filas[0])

    @action(detail=False, methods=["get"], url_path="clima/oni")
    def clima_oni(self, request):
        """Índice ONI histórico con su fase ENSO. `years` se pide en meses."""
        anios = _entero(request, "years", 10, 1, 80)
        return Response(evo.consultar(
            """
            SELECT year, month, oni_value, soi_value, pdo_value,
                   mjo_amplitude, enso_phase
            FROM clima_oni_monthly
            ORDER BY year DESC, month DESC LIMIT %(limite)s
            """,
            {"limite": anios * 12},
        ))

    @action(detail=False, methods=["get"], url_path="clima/prices")
    def clima_prices(self, request):
        anios = _entero(request, "years", 26, 1, 30)
        return Response(evo.consultar(
            """
            SELECT p.year, p.month, p.price_cop_kwh, p.enso_phase, o.oni_value
            FROM clima_price_monthly p
            LEFT JOIN clima_oni_monthly o
                   ON p.year = o.year AND p.month = o.month
            ORDER BY p.year DESC, p.month DESC LIMIT %(limite)s
            """,
            {"limite": anios * 12},
        ))

    @action(detail=False, methods=["get"], url_path="clima/precip")
    def clima_precip(self, request):
        anios = _entero(request, "years", 10, 1, 40)
        region = request.query_params.get("region", "Andina")
        return Response(evo.consultar(
            """
            SELECT year, month, precip_mm, anomaly_pct, climatology_mm
            FROM clima_precip_monthly
            WHERE region = %(region)s
            ORDER BY year DESC, month DESC LIMIT %(limite)s
            """,
            {"region": region, "limite": anios * 12},
        ))

    @action(detail=False, methods=["get"], url_path="health")
    def health(self, request):
        return self._evo("/health")

    # ── Carga masiva (admin) ──────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="clima/bulk-load")
    @log_endpoint(name="Operaciones | Mercado XM | EVO | Bulk load")
    def clima_bulk_load(self, request):
        """Carga masiva de índices climáticos e histórico de precios."""
        from apps.mercado_xm.services import evo_bulk

        try:
            cargados = evo_bulk.cargar(request.data)
        except Exception as exc:
            return Response(
                {"detail": f"Bulk load failed: {exc}"}, status=500
            )
        return Response({"status": "ok", "loaded": cargados})

    def get_permissions(self):
        # Solo la carga masiva exige admin; el resto es lectura autenticada.
        if self.action == "clima_bulk_load":
            self.required_role = ["admin"]
        return super().get_permissions()
