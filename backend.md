# Plataforma Operaciones Unergy — Backend

## Qué es esto
API REST para la plataforma interna de operaciones de Unergy. Gestiona proyectos
solares, clientes, contratos/servicios, fallas, generación, monitoreo, liquidaciones,
garantías, alertas, fronteras (CGM) y el módulo MEM. Integra varias APIs externas
(Unergy, Solenium/SunFactory, Quoia/Gaia, EVO) y corre tareas en segundo plano (MGS).

## Stack
- **Python 3.12** + **FastAPI 0.115**
- **SQLAlchemy 2.0** (ORM, estilo `Mapped`/`mapped_column`) + **psycopg3** (driver PostgreSQL)
- **Pydantic v2** + **pydantic-settings** (schemas y configuración por entorno)
- **python-jose** (JWT) + **bcrypt** (contraseñas)
- **APScheduler** (jobs en background: polling de alarmas MGS)
- **httpx** (cliente HTTP hacia APIs externas)
- **openpyxl** (Excel: informes/liquidaciones), **matplotlib** + **numpy** (gráficas en informes)
- **google-api-python-client** / **google-auth** (integración Google)
- **Alembic** — migraciones de esquema incrementales (ver "Migraciones de BD" abajo)
- **PostgreSQL 15** (Railway en producción, local en desarrollo)

## Estructura de carpetas
```
app/
├── main.py              # FastAPI app, CORS, lifespan, DDL idempotente al arranque,
│                        #   scheduler MGS, mounts estáticos (/static/uploads, /monitoreo), /health
├── core/
│   ├── config.py        # Settings (pydantic-settings): env vars, normaliza DATABASE_URL
│   ├── database.py      # Engine SQLAlchemy + SessionLocal + get_db()
│   └── security.py      # hash_password, verify_password, create_access_token, decode_token (HS256)
├── api/v1/
│   ├── router.py        # Registra TODOS los routers bajo prefix /api/v1
│   ├── auth.py          # POST /auth/token, GET /me, forgot/reset password, get_current_user(),
│   │                    #   usuarios_router (admin), soporta JWT y API Keys
│   ├── api_keys.py      # gestión de API keys
│   ├── dashboard.py · clientes.py · proyectos.py · portafolios.py
│   ├── fallas.py · generacion.py · generacion_solar.py · solar.py · monitoreo.py
│   ├── liquidaciones.py · garantias.py · representacion.py · om.py
│   ├── ppa.py · asic.py · fronteras.py · cumplimiento.py · mgs.py · reconectadores.py
│   ├── contratos_servicio.py · informes.py · notificaciones.py · mapa.py · proximos_energizar.py
│   └── evo_proxy.py · correlation.py     # proxies/lecturas a fuentes externas
├── models/              # Tablas SQLAlchemy 2.0 (un archivo por dominio)
│   ├── base.py          # Base (DeclarativeBase) + TimestampMixin (created_at/updated_at)
│   ├── usuarios.py      # Usuario, RolEnum
│   ├── clientes.py · proyectos.py · contratos.py · servicios.py
│   ├── fallas.py · generacion.py · om.py · mantenimientos.py · equipos.py
│   ├── liquidaciones.py · garantias.py · cumplimiento.py · fronteras.py
│   ├── asic.py · rec.py · promotor.py · documentos.py · informes.py
│   ├── gestion.py · notificaciones.py
│   └── ...
├── schemas/             # Pydantic schemas (request/response), un archivo por dominio
│   ├── common.py        # PaginatedResponse[T]
│   ├── usuarios.py · clientes.py · proyectos.py · fallas.py · contratos_servicio.py
│   └── cumplimiento.py · fronteras.py · garantias.py · generacion.py · mgs.py · notificaciones.py · om.py · ppa.py · asic.py
├── services/
│   ├── audit.py             # registro de auditoría
│   ├── correlation.py       # cruces con BD externas (origina / requests)
│   ├── email_service.py     # envío SMTP de informes aprobados
│   ├── om_calculator.py     # cálculos de O&M
│   └── mgs/                 # cliente + scheduler de alarmas MGS
├── utils/
│   ├── liquidaciones_loader.py   # carga de Excel de liquidaciones
│   └── proyecto_matching.py      # matching de nombres de proyecto
└── seeds/
    └── seed_data.py     # usuarios iniciales + catálogos (fallas, etc.)

alembic/                 # migraciones de esquema (env.py, versions/) — flujo oficial
init_db.py               # crea tablas base (create_all) + seed — bootstrap one-shot
```

## Migraciones de BD (importante)
El esquema se gestiona en **dos capas complementarias**, que `start.sh` ejecuta en orden
en cada arranque (ambas idempotentes):

1. **Tablas base** → las crea `Base.metadata.create_all()` en `init_db.py` a partir de
   los modelos de `app/models/`. Es el ÚNICO lugar que crea las tablas base; ninguna
   migración Alembic las crea (001..031 solo *alteran/extienden* tablas ya existentes).
   `create_all` ya NO corre dentro del lifespan de FastAPI, así que las réplicas de la
   app no ejecutan DDL al bootear.
2. **Cambios incrementales** (columnas/índices/enums/datos) → migraciones Alembic en
   `alembic/versions/`. `start.sh` corre `alembic upgrade head` después de `init_db.py`.

Orden de despliegue: `python init_db.py` (tablas base + seed) → `alembic upgrade head`.

### Cómo agregar un cambio de esquema
- **Columna/índice/enum nuevo en tabla existente** → crear una nueva migración Alembic
  `alembic/versions/NNN_descripcion.py` (con `down_revision` apuntando al head actual y un
  id de `revision` único — ver `tests/test_alembic_chain_integrity.py`). Usar
  `ALTER ... IF NOT EXISTS` / `ADD VALUE IF NOT EXISTS` para que sea re-ejecutable.
  **NO** agregar DDL a `app/main.py` ni a `init_db.py` (el viejo mecanismo de DDL en cada
  arranque — `_PENDING_DDLS` / `add_columns()` — se consolidó en
  `alembic/versions/031_baseline_all_ddls.py` y se eliminó).
- **Tabla nueva** → definir el modelo en `app/models/` (lo crea `create_all` en bootstrap)
  y, si necesitas aplicarla a una BD ya existente en producción, añadir también la migración
  Alembic correspondiente (`CREATE TABLE IF NOT EXISTS`).

## Cómo agregar un nuevo endpoint

### 1. Modelo (si la tabla no existe)
```python
# app/models/mi_modelo.py
from sqlalchemy import BigInteger, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class MiModelo(Base, TimestampMixin):
    __tablename__ = "mi_tabla"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    proyecto_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("proyectos.id"))
```
Importar el modelo en `app/models/__init__.py` para que `create_all` lo registre.

### 2. Schema Pydantic
```python
# app/schemas/mi_modelo.py
from pydantic import BaseModel

class MiModeloCreate(BaseModel):
    nombre: str
    proyecto_id: int

class MiModeloOut(MiModeloCreate):
    id: int
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
    db.add(obj); db.commit(); db.refresh(obj)
    return obj
```

### 4. Registrar en `app/api/v1/router.py`
```python
from app.api.v1 import mi_modulo
api_router.include_router(mi_modulo.router)
```

### 5. Migración (si agregaste tabla/columna)
Ver sección **Migraciones de BD** arriba. Tabla nueva → el modelo + `create_all` la crean
en bootstrap (y migración Alembic si hay que aplicarla a una BD de prod existente).
Columna/índice/enum nuevo → nueva migración Alembic en `alembic/versions/` (NO en
`init_db.py` ni en `app/main.py`).

## Autenticación
- Login: `POST /api/v1/auth/token` (form-urlencoded: `username`, `password`) → `access_token` JWT.
- Todos los endpoints protegidos llevan `_=Depends(get_current_user)`.
- El token va en el header `Authorization: Bearer <token>`.
- `get_current_user` acepta **JWT** o **API Key** (`api_keys.py`), y valida que el usuario esté activo.
- Hay flujo de **forgot/reset password** (`/auth/forgot-password`, `/auth/reset-password`).

## Roles disponibles
`admin` · `operaciones` · `monitoreo` · `liquidaciones` · `cgm` · `solo_lectura`
(definidos en `RolEnum`, `app/models/usuarios.py`).

Para restringir por rol:
```python
from fastapi import Depends, HTTPException, status
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario, RolEnum

def solo_admin(current: Usuario = Depends(get_current_user)):
    if current.rol != RolEnum.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Se requiere rol admin")
    return current
```

## Integraciones externas (vía `httpx`)
Configuradas en `config.py` y consumidas por routers/servicios:
- **API Unergy** (`UNERGY_*`) — bridge `_legacy` para datos de monitoreo/generación reales.
- **SunFactory / Solenium** (`SUNFACTORY_*`, `SOLENIUM_*`) — cronogramas EPC (próximos a
  energizarse) y datos de inversores FMO; auth OAuth2 username/password.
- **Quoia / Gaia** (`QUOIA_*`, `GAIA_*`) — fronteras CGM y medidores.
- **EVO Energy** (`EVO_*`) — DailySpot + clima (vía Tailscale).
- **SMTP** (`SMTP_*`) — envío de informes mensuales aprobados.
- **BD externas read-only** (`ORIGINA_DATABASE_URL`, `REQUESTSDB_DATABASE_URL`) — usadas
  por `services/correlation.py` para cruces de datos.

## Tareas en background — MGS
`app/services/mgs/` corre con **APScheduler** (arranca en el `lifespan` de `main.py`):
hace polling de alarmas cada `MGS_POLL_INTERVAL_MINUTES` (default 15) más jobs cron.
Se controla con `MGS_ENABLED` y `TIMEZONE` (America/Bogota).

## Almacenamiento de archivos
`STORAGE_BACKEND` = `local` (default, sirve en `/static/uploads`) o `s3`
(`S3_BUCKET`/`S3_ENDPOINT`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`).

## Variables de entorno (.env en la raíz del backend)
```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/operaciones
SECRET_KEY=<clave-segura-min-16-chars>
JWT_EXPIRE_MINUTES=480
ENVIRONMENT=development
FRONTEND_URL=http://localhost:5173

# Almacenamiento
STORAGE_BACKEND=local
STORAGE_LOCAL_PATH=./uploads

# Integraciones (opcionales en local; requeridas en prod según el módulo)
UNERGY_API_URL=https://api.unergy.io
UNERGY_ACCOUNT_ID=  UNERGY_LOGIN=  UNERGY_PASSWORD=
SUNFACTORY_USERNAME=  SUNFACTORY_PASSWORD=
SOLENIUM_USER=  SOLENIUM_PASS=
QUOIA_API_TOKEN=  GAIA_USER=  GAIA_PASS=
EVO_API_URL=  EVO_API_TOKEN=
ORIGINA_DATABASE_URL=  REQUESTSDB_DATABASE_URL=
SMTP_HOST=  SMTP_USER=  SMTP_PASSWORD=  SMTP_FROM=operaciones@unergy.io

# MGS scheduler
MGS_ENABLED=true
MGS_POLL_INTERVAL_MINUTES=15
TIMEZONE=America/Bogota
```
> `DATABASE_URL` se normaliza solo: `postgres://` y `postgresql://` se convierten a
> `postgresql+psycopg://` (Railway entrega el formato corto).

## Correr localmente
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python init_db.py      # crea tablas base (create_all) + seed inicial
alembic upgrade head   # aplica migraciones incrementales
uvicorn app.main:app --reload
# API en http://localhost:8000  ·  Docs en http://localhost:8000/docs  ·  Health: /health
```

## Producción
- **Plataforma:** Railway
- **Deploy:** automático al hacer push a `master` en GitHub
- **URL backend:** https://backend-production-63d8.up.railway.app
- **Docs producción:** https://backend-production-63d8.up.railway.app/docs

## Convenciones
- Un archivo por dominio en `app/models/`, `app/schemas/` y `app/api/v1/`.
- Modelos en estilo SQLAlchemy 2.0: `Mapped[...]` + `mapped_column`, heredando `TimestampMixin`.
- **IDs `BigInteger` autoincrement** (BIGSERIAL) — no UUID.
- Siempre usar `response_model` en los endpoints.
- Todo endpoint protegido lleva `Depends(get_current_user)`.
- Tablas base por `create_all` (modelos) en `init_db.py`; cambios incrementales por
  migración Alembic en `alembic/versions/` (DDL idempotente, NO en `app/main.py`/`init_db.py`).
- No usar `print()` para logs de aplicación — usar el logger de uvicorn (los `print` de
  `[startup]`/`[shutdown]` en `main.py` son trazas de arranque intencionales).
