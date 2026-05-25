import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.auth import get_current_user, _require_admin
from app.models.usuarios import Usuario

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


class ApiKeyCreate(BaseModel):
    usuario_id: int
    nombre: str
    scopes: list[str] = ["read"]


class ApiKeyOut(BaseModel):
    id: int
    usuario_id: int
    usuario_nombre: str | None = None
    nombre: str
    key_prefix: str
    scopes: list[str]
    activo: bool
    ultimo_uso: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    api_key: str


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _row_to_dict(row, usuario_nombre: str | None = None) -> dict:
    return {
        "id": row.id,
        "usuario_id": row.usuario_id,
        "usuario_nombre": usuario_nombre,
        "nombre": row.nombre,
        "key_prefix": row.key_prefix,
        "scopes": row.scopes or ["read"],
        "activo": row.activo,
        "ultimo_uso": row.ultimo_uso,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
    }


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db),
    _admin: Usuario = Depends(_require_admin),
):
    user = db.query(Usuario).filter(Usuario.id == data.usuario_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    raw_key = f"uop_{secrets.token_hex(32)}"
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:12]

    import json
    db.execute(
        text("""
            INSERT INTO api_keys (usuario_id, nombre, key_hash, key_prefix, scopes)
            VALUES (:uid, :nombre, :hash, :prefix, :scopes)
        """),
        {
            "uid": data.usuario_id,
            "nombre": data.nombre,
            "hash": key_hash,
            "prefix": key_prefix,
            "scopes": json.dumps(data.scopes),
        },
    )
    db.commit()

    row = db.execute(
        text("SELECT * FROM api_keys WHERE key_hash = :h"),
        {"h": key_hash},
    ).fetchone()

    result = _row_to_dict(row, user.nombre)
    result["api_key"] = raw_key
    return result


@router.get("/user/{usuario_id}")
def list_user_api_keys(
    usuario_id: int,
    db: Session = Depends(get_db),
    _admin: Usuario = Depends(_require_admin),
):
    user = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    rows = db.execute(
        text("SELECT * FROM api_keys WHERE usuario_id = :uid ORDER BY created_at DESC"),
        {"uid": usuario_id},
    ).fetchall()

    return [_row_to_dict(r, user.nombre) for r in rows]


@router.patch("/{key_id}/toggle")
def toggle_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _admin: Usuario = Depends(_require_admin),
):
    row = db.execute(text("SELECT * FROM api_keys WHERE id = :id"), {"id": key_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="API Key no encontrada")

    new_state = not row.activo
    db.execute(text("UPDATE api_keys SET activo = :a WHERE id = :id"), {"a": new_state, "id": key_id})
    db.commit()
    return {"id": key_id, "activo": new_state}


@router.delete("/{key_id}", status_code=204)
def delete_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _admin: Usuario = Depends(_require_admin),
):
    row = db.execute(text("SELECT id FROM api_keys WHERE id = :id"), {"id": key_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="API Key no encontrada")

    db.execute(text("DELETE FROM api_keys WHERE id = :id"), {"id": key_id})
    db.commit()


@router.get("/verify")
def verify_api_key_info(
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Endpoint to test that auth works — returns current user info."""
    return {
        "user_id": current.id,
        "nombre": current.nombre,
        "email": current.email,
        "rol": current.rol.value,
    }
