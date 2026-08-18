from pydantic import BaseModel


class MandatoOut(BaseModel):
    id: int
    proyecto: str
    tercero: str
    periodo: str
    tipo: str
    cmu: str | None
    cmu_anterior: str | None
    estado: str
    comentario: str | None
    fecha_envio: str | None
    fecha_firma: str | None
    drive_url: str | None
