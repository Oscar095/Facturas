"""Autenticación: hash de contraseñas (PBKDF2 stdlib) y JWT."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Usuario

_ITERACIONES = 200_000
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── contraseñas ────────────────────────────────────────────────────────────────
def hash_clave(clave: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), salt, _ITERACIONES)
    return f"pbkdf2_sha256${_ITERACIONES}${salt.hex()}${dk.hex()}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        _, iteraciones, salt_hex, hash_hex = almacenado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", clave.encode(), bytes.fromhex(salt_hex), int(iteraciones))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── JWT ─────────────────────────────────────────────────────────────────────────
def crear_token(usuario: Usuario) -> str:
    payload = {
        "sub": str(usuario.id),
        "email": usuario.email,
        "rol": usuario.rol,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expira_minutos),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def usuario_actual(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> Usuario:
    cred_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise cred_error
    usuario = db.get(Usuario, user_id)
    if usuario is None or not usuario.activo:
        raise cred_error
    return usuario


def requiere_rol(*roles: str):
    def dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(status_code=403, detail="No autorizado para esta acción")
        return usuario

    return dependencia


def verificar_api_key(x_api_key: str | None) -> None:
    if not settings.jobs_api_key or x_api_key != settings.jobs_api_key:
        raise HTTPException(status_code=401, detail="API key inválida")
