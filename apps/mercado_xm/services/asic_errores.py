"""Errores de las reglas de GESCON/ASIC.

Un servicio de dominio no conoce HTTP, así que levanta estas y la vista las
traduce. Hay tres porque el contrato actual usa tres códigos distintos y cada
uno significa algo diferente para quien radica ante XM.
"""


class ReglaAsic(ValueError):
    """422 — los datos son coherentes en forma pero rompen una regla."""


class NoEncontrado(LookupError):
    """404 — el contrato o el registro que se pide no existe."""


class Bloqueado(RuntimeError):
    """409 — la operación es válida pero hay algo que depende de estos datos."""
