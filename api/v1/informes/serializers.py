"""Serializers de informes guardados."""

from rest_framework import serializers

from apps.plataforma import models as pl_models

TIPOS = ("op", "fmo", "port", "ranking", "pm")
ESTADOS = ("borrador", "revisado", "aprobado")


class ComentarioSerializer(serializers.Serializer):
    id = serializers.CharField()
    autor_email = serializers.CharField()
    autor_nombre = serializers.CharField(allow_null=True, required=False)
    mensaje = serializers.CharField()
    created_at = serializers.CharField()
    resuelto = serializers.BooleanField(default=False)
    resuelto_en = serializers.CharField(allow_null=True, required=False)
    resuelto_por_email = serializers.CharField(allow_null=True, required=False)
    resuelto_por_nombre = serializers.CharField(allow_null=True, required=False)
    respuesta = serializers.CharField(allow_null=True, required=False)


class InformeSerializer(serializers.ModelSerializer):
    """Listado. NO incluye `html_content`: son cientos de KB por fila."""

    comentarios = serializers.SerializerMethodField()
    miembros = serializers.SerializerMethodField()

    class Meta:
        model = pl_models.InformeGuardado
        fields = [
            "id", "tipo", "sub_project", "periodo_desde", "periodo_hasta",
            "periodo_display", "proyecto_nombre", "estado",
            "creado_por_nombre", "editado_por_nombre", "aprobado_por_nombre",
            "enviado_por_nombre", "creado_en", "editado_en", "aprobado_en",
            "correo_enviado", "correo_enviado_en", "comentarios", "miembros",
        ]

    def get_comentarios(self, obj) -> list:
        # Las filas anteriores a la migración 021 pueden tener NULL.
        return obj.comentarios if isinstance(obj.comentarios, list) else []

    def get_miembros(self, obj) -> list:
        """Los miembros SIN `html_inline`.

        Ese campo puede pesar cientos de KB y solo lo usa el backend para
        componer y enviar; el frontend no lo necesita.
        """
        if not isinstance(obj.miembros, list):
            return []
        return [
            {k: v for k, v in m.items() if k != "html_inline"}
            for m in obj.miembros if isinstance(m, dict)
        ]


class InformeDetalleSerializer(InformeSerializer):
    class Meta(InformeSerializer.Meta):
        fields = InformeSerializer.Meta.fields + ["html_content", "charts_data"]


class UpsertSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=TIPOS)
    sub_project = serializers.CharField()
    periodo_desde = serializers.CharField()
    periodo_hasta = serializers.CharField()
    periodo_display = serializers.CharField(required=False, allow_null=True)
    proyecto_nombre = serializers.CharField(required=False, allow_null=True)
    html_content = serializers.CharField(allow_blank=True)
    # Puede llegar como dict o como cadena JSON; se normaliza en `validate`.
    charts_data = serializers.JSONField(required=False, allow_null=True)
    miembros = serializers.ListField(required=False, allow_null=True)

    def validate_charts_data(self, valor):
        """Una cadena JSON se parsea; si no es válida, se descarta.

        Llega del frontend como el volcado del `rptChartQueue` y a veces viaja
        serializado. Guardar la cadena cruda en el JSONB rompería a quien lo lea.
        """
        import json

        if isinstance(valor, str):
            try:
                return json.loads(valor)
            except (ValueError, TypeError):
                return None
        return valor


class EstadoSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=ESTADOS)


class SeccionSerializer(serializers.Serializer):
    sub_project = serializers.CharField()
    html_content = serializers.CharField(allow_blank=True)


class ComentarioCrearSerializer(serializers.Serializer):
    mensaje = serializers.CharField()


class ComentarioResolverSerializer(serializers.Serializer):
    respuesta = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
