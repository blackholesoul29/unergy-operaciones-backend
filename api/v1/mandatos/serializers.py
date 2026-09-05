"""Serializers de mandatos."""

from rest_framework import serializers

from apps.mandatos import models as md_models


class InversionistaSerializer(serializers.ModelSerializer):
    class Meta:
        model = md_models.MandatoInversionista
        fields = ["id", "nombre", "activo"]


class MandatoCrearSerializer(serializers.ModelSerializer):
    class Meta:
        model = md_models.Mandato
        fields = [
            "cmu", "periodo", "proyecto", "tercero", "inversionista",
            "estado", "observacion",
        ]
        extra_kwargs = {
            c: {"required": False} for c in fields if c not in ("cmu", "periodo")
        }


class MandatoActualizarSerializer(serializers.ModelSerializer):
    class Meta:
        model = md_models.Mandato
        fields = [
            "proyecto", "tercero", "inversionista", "estado", "observacion",
            "fecha_envio_revisoria", "fecha_firmado",
            "fecha_envio_inversionista", "correo_ref_revisoria",
            "correo_ref_envio",
        ]
        extra_kwargs = {c: {"required": False} for c in fields}


class AsociarPdfSerializer(serializers.Serializer):
    # Solo el NOMBRE, nunca una ruta: ver `pdfs.ruta_de_nombre`.
    nombre = serializers.CharField()
