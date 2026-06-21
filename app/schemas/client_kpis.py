"""Schema de KPIs del panel de resumen del cliente.

Los KPIs se calculan al vuelo (no se persisten); ver el endpoint
`GET /api/v1/clientes/{id}/resumen` en `app/api/v1/clientes.py`.
"""
from pydantic import BaseModel


class ClienteKPIsOut(BaseModel):
    # MWh netos entregados durante el último mes calendario completo.
    mwh_netos_mes_anterior: float
    # Proyectos del cliente en operación (servicios activos).
    servicios_activos: int
    # Semáforo de cumplimiento PPA:
    #   'verde' | 'amarillo' | 'rojo'  → hay contratos, peor estado de los contratos.
    #   'sin_contratos'                → el cliente no tiene contratos PPA.
    estado_cumplimiento_ppa: str
    # Mes medido en formato 'YYYY-MM' (el último mes completo).
    periodo: str | None = None
    # Número de contratos PPA vigentes considerados para el semáforo.
    num_contratos_ppa: int = 0
