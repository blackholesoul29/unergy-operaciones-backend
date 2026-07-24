"""Schemas del listado de Estados de Resultados almacenados en Drive."""
from pydantic import BaseModel


class ArchivoER(BaseModel):
    id: str
    nombre: str
    tipo: str                 # estado_resultados | cruce_facturas | otro
    descripcion: str          # cliente + proyecto (vacío en el cruce, que es del período)
    mes: int | None = None
    anio: int | None = None
    version: str | None = None  # solo en cruce de facturas: txf, tx3, ...
    modificado: str | None = None
    tamano: int | None = None
    link: str | None = None   # webViewLink: abre el xlsx en el visor de Drive
    es_copia: bool = False    # duplicado de Drive ("Copia de ...")


class PeriodoER(BaseModel):
    mes: int
    anio: int
    total: int


class ArchivosERResponse(BaseModel):
    total_carpeta: int        # archivos en la carpeta, sin filtrar
    total_filtrados: int      # los que pasan los filtros (antes de recortar por limite)
    truncado: bool            # True si se recortó la lista por `limite`
    periodos: list[PeriodoER]
    archivos: list[ArchivoER]
