"""Serializers de operadores de red."""

from rest_framework import serializers

from apps.fronteras import models as fr_models


class ContactoSerializer(serializers.ModelSerializer):
    operador_red_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = fr_models.OperadorRedContacto
        fields = ["id", "operador_red_id", "email", "nombre", "created_at"]


class ContactoEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = fr_models.OperadorRedContacto
        fields = ["email", "nombre"]


class ContactoUpdateSerializer(ContactoEscrituraSerializer):
    class Meta(ContactoEscrituraSerializer.Meta):
        extra_kwargs = {"email": {"required": False}, "nombre": {"required": False}}


class OperadorRedSerializer(serializers.ModelSerializer):
    """`fronteras_vinculadas` lo anota el queryset; acá se lee como un campo más."""

    contactos = ContactoSerializer(many=True, read_only=True)
    fronteras_vinculadas = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = fr_models.OperadorRed
        fields = [
            "id", "nombre_legal", "nombre_comercial", "contactos",
            "fronteras_vinculadas", "created_at", "updated_at",
        ]


class OperadorRedEscrituraSerializer(serializers.ModelSerializer):
    class Meta:
        model = fr_models.OperadorRed
        fields = ["nombre_legal", "nombre_comercial"]


class OperadorRedUpdateSerializer(OperadorRedEscrituraSerializer):
    class Meta(OperadorRedEscrituraSerializer.Meta):
        extra_kwargs = {
            "nombre_legal": {"required": False},
            "nombre_comercial": {"required": False},
        }
