import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from app.core.database import get_db
from app.core.security import verify_password, create_access_token, decode_token
from app.models.usuarios import Usuario
from app.schemas.usuarios import TokenResponse, UsuarioOut, UsuarioCreate, UsuarioUpdate
from app.core.security import hash_password

router = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    user = db.query(Usuario).filter(Usuario.id == int(payload.get("sub"))).first()
    if not user or not user.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo o no encontrado")
    from app.services.audit import set_audit_user
    set_audit_user(user.id, user.nombre)
    return user


@router.post("/token", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == form.username).first()
    if not user or not user.password_hash or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
    if not user.activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
    user.ultimo_acceso = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token({
        "sub": str(user.id),
        "rol": user.rol.value,
        "nombre": user.nombre,
        "email": user.email,
    })
    return {"access_token": token}


@router.get("/me")
def me(current: Usuario = Depends(get_current_user)):
    return UsuarioOut.model_validate(current).model_dump(mode="json")


# ── Password recovery ───────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Generate a time-limited reset token (1hr) and send via email."""
    user = db.query(Usuario).filter(Usuario.email == data.email).first()
    if not user:
        # Return 200 even if user not found to prevent email enumeration
        return {"msg": "Si el correo existe, recibirás instrucciones para restablecer tu contraseña."}

    token = uuid.uuid4().hex
    user.password_reset_token = token
    user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()

    # Send reset email
    try:
        from app.services.email_service import send_reset_password_email
        send_reset_password_email(to_email=user.email, token=token)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error enviando email de reset: %s", exc)

    return {"msg": "Si el correo existe, recibirás instrucciones para restablecer tu contraseña."}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Validate reset token and update password."""
    user = db.query(Usuario).filter(
        Usuario.password_reset_token == data.token,
    ).first()
    if not user:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")
    if not user.password_reset_expires or user.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Token inválido o expirado")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")

    user.password_hash = hash_password(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    db.commit()
    return {"msg": "Contraseña actualizada exitosamente"}


# Separate router for user listing (not under /auth prefix)
usuarios_router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


def _require_admin(current: Usuario = Depends(get_current_user)):
    if current.rol.value != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Se requiere rol admin")
    return current


@usuarios_router.get("")
def list_usuarios(
    size: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    total = db.query(func.count(Usuario.id)).scalar()
    users = db.query(Usuario).order_by(Usuario.nombre).limit(size).all()
    return {
        "items": [{"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol.value, "activo": u.activo} for u in users],
        "total": total,
    }


@usuarios_router.post("", response_model=UsuarioOut, status_code=201)
def create_usuario(
    data: UsuarioCreate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    if db.query(Usuario).filter(Usuario.email == data.email).first():
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")
    user = Usuario(
        email=data.email,
        nombre=data.nombre,
        rol=data.rol,
        activo=data.activo,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@usuarios_router.patch("/{id}", response_model=UsuarioOut)
def update_usuario(
    id: int,
    data: UsuarioUpdate,
    db: Session = Depends(get_db),
    _=Depends(_require_admin),
):
    user = db.query(Usuario).filter(Usuario.id == id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if data.nombre is not None:
        user.nombre = data.nombre
    if data.rol is not None:
        user.rol = data.rol
    if data.activo is not None:
        user.activo = data.activo
    if data.password is not None:
        user.password_hash = hash_password(data.password)
    db.commit()
    db.refresh(user)
    return user
