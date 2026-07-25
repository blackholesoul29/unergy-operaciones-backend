from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class XMDescargaRequest(BaseModel):
    ftp_usuario: str
    ftp_clave: str
    ftp_host: str = "xmftps.xm.com.co"
    tipo: str
    extension: str
    fecha_inicio: date
    fecha_fin: date
    enriquecer: bool = False
    # Para tipos que se filtran por agente (tgrl): UNGG (generador) o UNGC
    # (comercializador). Se ignora para los tipos que filtran por planta.
    agente_filtro: str = "UNGG"


class XMJobResponse(BaseModel):
    job_id: str


class XMJobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    estado: Literal["descargando", "unificando", "exportando", "listo", "error"]
    archivos_procesados: int
    archivos_totales: int
    archivos_faltantes: list[str]
    codigos_sin_match: list[str]
    meses_fronteras_usados: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
