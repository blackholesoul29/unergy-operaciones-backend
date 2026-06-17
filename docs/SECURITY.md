# Seguridad de contraseñas — Plataforma Operaciones

> Las contraseñas iniciales son **aleatorias** y **deben cambiarse en el primer
> acceso**. No existen contraseñas por defecto en el código.

## Resumen

Se eliminó la contraseña hardcodeada `Unergy2025!` que estaba en el seed y en el
script de migración (`migrate_fallas_desde_sheets.py`). Ahora:

- Cada usuario sembrado recibe una contraseña aleatoria fuerte
  (`app/utils/password_generator.generate_secure_password`, basada en `secrets`).
- Todo usuario nuevo (y los existentes con la contraseña filtrada) queda con
  `force_password_reset = True` y debe cambiarla antes de usar la API.
- Los scripts ya no llevan credenciales: se leen del entorno.

## Modelo de datos

`usuarios` añade (migración alembic `024`, también vía DDL idempotente de arranque):

| Columna | Tipo | Default | Para qué |
|---|---|---|---|
| `force_password_reset` | BOOLEAN | `TRUE` | Bloquea la API hasta cambiar la contraseña |
| `password_changed_at` | TIMESTAMPTZ | NULL | Auditoría del último cambio |
| `password_hash_version` | INTEGER | `1` | Versión del algoritmo de hashing (1 = bcrypt) |

## Flujo de cambio obligatorio

1. `POST /api/v1/auth/token` → login (devuelve JWT aunque haya reset pendiente).
2. Cualquier endpoint protegido devuelve **403 «Debe cambiar su contraseña
   primero»** mientras `force_password_reset = True`.
   - Rutas permitidas en ese estado: `/auth/change-password`, `/auth/me`,
     `/auth/token`.
3. `POST /api/v1/auth/change-password` con `{old_password, new_password}`:
   - valida la contraseña actual,
   - exige complejidad (mín. 10 caracteres, ≥3 clases de carácter),
   - rechaza reutilizar la actual,
   - pone `force_password_reset = False` y `password_changed_at = now()`,
   - está limitado por tasa (5 intentos / 5 min por usuario).

## Seed

```bash
# Desarrollo: imprime las contraseñas iniciales en stdout
python -m app.seeds.seed_data --dev

# Producción: cifra las contraseñas con Fernet a app/seeds/seed_passwords.json.enc
SEED_FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  python -m app.seeds.seed_data
```

- En producción se requiere `SEED_FERNET_KEY`; si falta, el seed aborta en vez
  de filtrar contraseñas.
- `seed_passwords.json.enc` está en `.gitignore` y **nunca** debe versionarse.
  Descífralo con la misma `SEED_FERNET_KEY` y entrega cada contraseña por un
  canal seguro; bórralo después.
- `ADMIN_INITIAL_PASSWORD` (opcional): si en el futuro se necesita una
  contraseña inicial fija para un admin concreto, defínela por entorno — nunca
  en el código.

## Script de migración (`migrate_fallas_desde_sheets.py`)

Credenciales solo desde el entorno (o `.env`):

```bash
# Recomendado: API key de cuenta de servicio (tabla api_keys)
ADMIN_API_KEY=... python migrate_fallas_desde_sheets.py --dry-run

# Alternativa: usuario/contraseña de un admin real
ADMIN_USER=tu@unergy.io ADMIN_PASS=... python migrate_fallas_desde_sheets.py
```

La autenticación por API key (cabecera `X-API-Key`) **no** está sujeta al
bloqueo de `force_password_reset`, por lo que es la vía indicada para
integraciones automatizadas.

## Acción operativa pendiente

La contraseña `Unergy2025!` estuvo en el repositorio: **rotar de inmediato** las
credenciales de cualquier cuenta que la haya usado (p. ej. `juanjose@unergy.io`)
y purgarla del historial si aplica.
