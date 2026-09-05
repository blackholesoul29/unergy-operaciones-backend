"""Serializers del listado de Estados de Resultados.

Ninguno es `ModelSerializer`: lo que se lista son archivos de Drive, no filas de
la base. El período y la versión salen del NOMBRE del archivo
(`drive.parse_nombre_er`), no de metadatos de Drive.
"""

from rest_framework import serializers


class ArchivoERSerializer(serializers.Serializer):
    id = serializers.CharField()
    nombre = serializers.CharField()
    tipo = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    mes = serializers.IntegerField(allow_null=True)
    anio = serializers.IntegerField(allow_null=True)
    version = serializers.CharField(allow_null=True)
    modificado = serializers.CharField(allow_null=True)
    tamano = serializers.IntegerField(allow_null=True)
    link = serializers.CharField(allow_null=True)
    es_copia = serializers.BooleanField()


class PeriodoERSerializer(serializers.Serializer):
    mes = serializers.IntegerField()
    anio = serializers.IntegerField()
    total = serializers.IntegerField()


class ArchivosERSerializer(serializers.Serializer):
    total_carpeta = serializers.IntegerField()
    total_filtrados = serializers.IntegerField()
    truncado = serializers.BooleanField()
    periodos = PeriodoERSerializer(many=True)
    versiones = serializers.ListField(child=serializers.CharField())
    archivos = ArchivoERSerializer(many=True)
