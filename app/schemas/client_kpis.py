"""Schema de KPIs del panel de resumen del cliente.

Los KPIs se calculan al vuelo (no se persisten); ver el endpoint
`GET /api/v1/clientes/{id}/resumen` en `app/api/v1/clientes.py`.
"""
from pydantic import BaseModel


class ClienteKPIsOut(BaseModel):
    # MWh netos entregados durante el último mes calendario completo.
    mwh_net_last_month: float
    # Proyectos del cliente en operación (servicios activos).
    active_services_count: int
    # Semáforo de cumplimiento PPA: 'Green' | 'Yellow' | 'Red' | 'N/A'.
    ppa_compliance_status: str
    # Mes medido en formato 'YYYY-MM' (el último mes completo).
    periodo: str | None = None
    # Número de contratos PPA vigentes considerados para el semáforo.
    ppa_contracts_count: int = 0
