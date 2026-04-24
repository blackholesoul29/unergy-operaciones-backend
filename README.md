# Plataforma Operaciones — Unergy

Sistema interno para gestión de proyectos, clientes, fallas, liquidaciones y más.

## Stack

- **Backend:** FastAPI + SQLAlchemy 2.0 + PostgreSQL 16
- **Frontend:** Vue 3 + PrimeVue 4 + Pinia + Tailwind CSS
- **Infraestructura:** Docker Compose

---

## Arranque local (< 10 minutos)

### 1. Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y corriendo
- Git

### 2. Clonar y configurar variables

```bash
git clone <repo-url>
cd "Plataforma Operaciones/Backend Operaciones"
cp .env.example .env
# Edita .env si quieres cambiar la clave secreta (opcional para local)
```

### 3. Levantar la base de datos

```bash
docker compose up -d postgres
```

### 4. Crear tablas y cargar datos iniciales

```bash
cd backend
pip install -r requirements.txt
python init_db.py
cd ..
```

> Esto crea todas las tablas y carga los usuarios, catálogos de fallas y requisitos Promotor.

### 5. Levantar todos los servicios

```bash
docker compose up --build
```

| Servicio   | URL                        |
|------------|----------------------------|
| Frontend   | http://localhost:5173      |
| Backend    | http://localhost:8000      |
| API Docs   | http://localhost:8000/docs |

---

## Usuarios iniciales

| Nombre         | Email                  | Contraseña    | Rol          |
|----------------|------------------------|---------------|--------------|
| Juan José      | juanjose@unergy.io     | Unergy2025!   | admin        |
| Laura          | laurah@unergy.io       | Unergy2025!   | monitoreo    |
| Jessica        | jessica@unergy.io      | Unergy2025!   | cgm          |
| Nicolás        | nicolas@unergy.io      | Unergy2025!   | operaciones  |
| Eduardo        | eduardo@unergy.io      | Unergy2025!   | operaciones  |
| Víctor         | victor@unergy.io       | Unergy2025!   | liquidaciones|

---

## Estructura del proyecto

```
Backend Operaciones/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py              # Entrada FastAPI
│   │   ├── core/                # Config, DB, seguridad
│   │   ├── models/              # 43 tablas SQLAlchemy
│   │   ├── schemas/             # Pydantic v2
│   │   ├── api/v1/              # Endpoints REST
│   │   └── seeds/               # Datos iniciales
│   ├── alembic/                 # Migraciones
│   ├── init_db.py               # Script arranque inicial
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── api/                 # Axios client
    │   ├── stores/              # Pinia (auth)
    │   ├── router/              # Vue Router + guards
    │   ├── components/          # Sidebar, Topbar
    │   └── views/               # Módulos por área
    └── package.json
```

---

## Flujo de trabajo colaborativo

Cada colaborador trabaja en su propia rama de feature:

```bash
git checkout -b feature/laura-fallas
# Trabajo...
git push origin feature/laura-fallas
# → Pull Request a dev → revisión → merge
```

La rama `main` es producción. La rama `dev` es integración.

---

## Migraciones (Alembic)

```bash
cd backend
# Generar migración luego de cambiar modelos:
alembic revision --autogenerate -m "descripcion del cambio"
# Aplicar:
alembic upgrade head
```
