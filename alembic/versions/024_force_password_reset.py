"""Force password reset on first login + password change tracking

Añade columnas de seguridad a `usuarios`:
  - force_password_reset: obliga a cambiar la contraseña en el primer acceso.
  - password_changed_at: marca de tiempo del último cambio.
  - password_hash_version: versión del algoritmo de hashing (1 = bcrypt).

Motivo: la contraseña semilla "Unergy2025!" estaba hardcodeada y se filtró,
por lo que todos los usuarios existentes deben rotarla. Todas las sentencias
son idempotentes (IF NOT EXISTS) para coexistir con el DDL de arranque.

Revision ID: 024
Revises: 023
Create Date: 2026-06-17
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS force_password_reset BOOLEAN NOT NULL DEFAULT TRUE"
    )
    op.execute(
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_hash_version INTEGER NOT NULL DEFAULT 1"
    )
    # Forzar rotación de la contraseña filtrada en todos los usuarios existentes.
    op.execute(
        "UPDATE usuarios SET force_password_reset = TRUE "
        "WHERE password_hash IS NOT NULL AND password_changed_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE usuarios DROP COLUMN IF EXISTS password_hash_version")
    op.execute("ALTER TABLE usuarios DROP COLUMN IF EXISTS password_changed_at")
    op.execute("ALTER TABLE usuarios DROP COLUMN IF EXISTS force_password_reset")
