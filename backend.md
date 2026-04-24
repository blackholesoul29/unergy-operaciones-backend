# Plataforma Operaciones Unergy — Backend

## Qué es esto
API REST para la plataforma interna de operaciones de Unergy. Gestiona proyectos solares, clientes, fallas, liquidaciones, contratos, equipos y más.

## Stack
- **Python 3.12** + **FastAPI 0.115**
- **SQLAlchemy 2.0** (ORM) + **psycopg3** (driver PostgreSQL)
- **Pydantic v2** (validación de schemas)
- **python-jose** (JWT) + **bcrypt** (contraseñas)
- **Alembic** (migraciones de BD)
- **PostgreSQL 15** (Railway en producción, local en desarrollo)

## Estructura de carpetas
```
app/
├── main.py              # FastAPI app, CORS
├── core/
│   ├── config.py        # Variables de entorno (pydantic-settings)
│   ├── database.py      # Engine SQLAlchemy + get_db()
│   └── security.py      # hash_password, verify_password, create_access_token, decode_token
├── api/v1/
│   ├── router.py        # Registra todos los routers
│   ├── auth.py          # POST /token, GET /me, get_current_user()
│   ├── clientes.py      # CRUD /clientes
│   └── proyectos.py     # CRUD /proyectos
├── models/              # Tablas SQLAlchemy (un archivo por dominio)
│   ├── base.py          # Base declarativa + TimestampMixin
│   ├── usuarios.py      # Usuario, RolEnum
│   ├── clientes.py      # Cliente, TipoClienteEnum
│   ├── proyectos.py     # Proyecto, EstadoProyectoEnum
│   ├── fallas.py        # Falla + catálogos (categoría, tipo, estado, prioridad, resolución)
│   ├── contratos.py
│   ├── liquidaciones.py
│   ├── equipos.py
│   ├── fronteras.py
│   ├── mantenimientos.py
│   ├── documentos.py
│   ├── promotor.py
│   ├── rec.py
│   ├── asic.py
│   └── servicios.py
├── schemas/             # Pydantic schemas (request/response)
│   ├── common.py        # PaginatedResponse[T]
│   ├── usuarios.py      # TokenResponse, UsuarioOut
│   ├── clientes.py      # ClienteCreate, ClienteOut
│   └── proyectos.py     # ProyectoCreate, ProyectoOut
└── seeds/
    └── seed_data.py     # Usuarios iniciales + catálogos de fallas
```

## Cómo agregar un nuevo endpoint

### 1. Modelo (si la tabla no existe)
```python
# app/models/mi_modelo.py
from app.models.base import Base, TimestampMixin
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

class MiModelo(Base, TimestampMixin):
    __tablename__ = "mi_tabla"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String, nullable=False)
    proyecto_id = Column(UUID(as_uuid=True), ForeignKey("proyectos.id"))
```

Agregar al `app/models/__init__.py` para que se registre.

### 2. Schema Pydantic
```python
# app/schemas/mi_modelo.py
from pydantic import BaseModel
from uuid import UUID

class MiModeloCreate(BaseModel):
    nombre: str
    proyecto_id: UUID

class MiModeloOut(MiModeloCreate):
    id: UUID
    model_config = {"from_attributes": True}
```

### 3. Router
```python
# app/api/v1/mi_modulo.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.mi_modelo import MiModelo
from app.schemas.mi_modelo import MiModeloCreate, MiModeloOut

router = APIRouter(prefix="/mi-modulo", tags=["Mi Módulo"])

@router.get("/", response_model=list[MiModeloOut])
def listar(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(MiModelo).all()

@router.post("/", response_model=MiModeloOut)
def crear(data: MiModeloCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    obj = MiModelo(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
```

### 4. Registrar en router.py
```python
from app.api.v1.mi_modulo import router as mi_router
api_router.include_router(mi_router)
```

### 5. Migración de BD
```bash
alembic revision --autogenerate -m "add mi_tabla"
alembic upgrade head
```

## Autenticación
Todos los endpoints deben tener `_=Depends(get_current_user)` para requerir JWT.

El token se pasa en el header: `Authorization: Bearer <token>`

## Roles disponibles
`admin` · `operaciones` · `monitoreo` · `liquidaciones` · `cgm`

Para restringir por rol:
```python
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario, RolEnum

def solo_admin(current: Usuario = Depends(get_current_user)):
    if current.rol != RolEnum.admin:
        raise HTTPException(403, "Solo admins")
    return current
```

## Variables de entorno (.env local)
```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/operaciones
SECRET_KEY=dev-secret-key
JWT_EXPIRE_MINUTES=480
ENVIRONMENT=development
FRONTEND_URL=http://localhost:5173
```

## Correr localmente
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python init_db.py      # crea tablas y seed
uvicorn app.main:app --reload
# API disponible en http://localhost:8000
# Docs en http://localhost:8000/docs
```

## Producción
- **Plataforma:** Railway
- **Deploy:** automático al hacer push a `master` en GitHub
- **URL backend:** https://backend-production-63d8.up.railway.app
- **Docs producción:** https://backend-production-63d8.up.railway.app/docs

## Convenciones
- Un archivo de modelo por dominio en `app/models/`
- Un archivo de schema por dominio en `app/schemas/`
- Un archivo de router por dominio en `app/api/v1/`
- Siempre usar `response_model` en los endpoints
- Los IDs son UUID (PostgreSQL `uuid` nativo)
- Todas las tablas heredan `TimestampMixin` (created_at, updated_at automáticos)
- No usar `print()` para logs — usar el logger de uvicorn
