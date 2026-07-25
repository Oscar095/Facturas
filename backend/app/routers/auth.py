from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Usuario
from ..schemas import CambioClave, Token, UsuarioYo
from ..security import crear_token, hash_clave, permisos_de, usuario_actual, verificar_clave

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(datos: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    usuario = db.execute(
        select(Usuario).where(Usuario.email == datos.username.lower())
    ).scalar_one_or_none()
    if usuario is None or not usuario.activo or not verificar_clave(datos.password, usuario.hash_clave):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    return Token(
        access_token=crear_token(usuario),
        rol=usuario.rol,
        nombre=usuario.nombre,
    )


@router.get("/yo", response_model=UsuarioYo)
def yo(usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    salida = UsuarioYo.model_validate(usuario)
    salida.permisos = permisos_de(db, usuario)
    return salida


@router.post("/cambiar-clave")
def cambiar_clave(datos: CambioClave, usuario: Usuario = Depends(usuario_actual),
                  db: Session = Depends(get_db)):
    if not verificar_clave(datos.clave_actual, usuario.hash_clave):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    usuario.hash_clave = hash_clave(datos.clave_nueva)
    db.commit()
    return {"ok": True}
