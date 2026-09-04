"""Entrada de `POST /reporte-cgm/enviar`.

La respuesta la arma `apps.energia.services.cgm_envio`, que ya devuelve la
forma de `EnviarReporteCGMResponse`.
"""

from rest_framework import serializers

from api.exceptions import NoProcesable

# Tope de tamaño de rango -- sin esto, una request con fecha_inicio/fecha_fin
# muy separadas dispara una llamada paginada a Quoia por CADA frontera
# involucrada, cubriendo todo ese rango (ver `fetch_filas_rango`), y arma un
# Excel/correo con esa cantidad de filas -- sin guardrail, un rango de
# meses/años multiplicado por "Operaciones Unergy" (~300 fronteras) puede
# tardar minutos o agotar memoria. 92 días (~3 meses) cubre con margen el uso
# real (un día, o el mes-a-la-fecha en curso) sin permitir un rango
# arbitrariamente grande (auditoría CGM 2026-08-26, finding #5).
RANGO_MAXIMO_DIAS = 92


class DestinatarioSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=["operador", "cliente"])
    id = serializers.IntegerField()
    # None = todas las fronteras del destinatario; lista (incluso vacía) =
    # filtrar solo a esos proyecto_id.
    proyectos = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True,
        default=None,
    )


class EnviarSerializer(serializers.Serializer):
    fecha_inicio = serializers.DateField()
    fecha_fin = serializers.DateField()
    destinatarios = DestinatarioSerializer(many=True)

    def validate(self, datos):
        dias = abs((datos["fecha_fin"] - datos["fecha_inicio"]).days) + 1
        if dias > RANGO_MAXIMO_DIAS:
            # 422 y no 400: es lo que devolvía el `model_validator` de Pydantic.
            raise NoProcesable(
                f"El rango de fechas no puede superar {RANGO_MAXIMO_DIAS} días "
                f"(pediste {dias})."
            )
        return datos
