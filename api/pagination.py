"""Paginacion base — el contrato de respuesta que ya consume el frontend.

FastAPI devuelve hoy `{items, total, page, size}` en los listados paginados. DRF
devuelve `{count, next, previous, results}`. Mantener el contrato es parte de
"los mismos endpoints": un cambio de nombres de clave rompe el frontend igual
que un cambio de ruta.
"""

from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class BasePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "size"
    page_query_param = "page"
    max_page_size = 500

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("items", data),
                    ("total", self.page.paginator.count),
                    ("page", self.page.number),
                    ("size", self.get_page_size(self.request)),
                ]
            )
        )


class PaginacionConPaginas(BasePagination):
    """`{items, total, page, size, pages}` — el `PaginatedResponse` de Pydantic.

    Los listados que FastAPI declara con `response_model=PaginatedResponse[X]`
    incluyen `pages`; los que devuelven el dict a mano, no. Son dos contratos
    distintos que ya están en producción, así que se conservan los dos.
    """

    def get_paginated_response(self, data):
        respuesta = super().get_paginated_response(data)
        total = self.page.paginator.count
        tamano = self.get_page_size(self.request)
        respuesta.data["pages"] = -(-total // tamano) if tamano else 0
        return respuesta
