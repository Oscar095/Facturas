from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Usuario
from ..schemas import UsuarioActualizar, UsuarioCrear, UsuarioOut
from ..security import hash_clave, requiere_rol

router = APIRouter(prefix="/api/usuarios", tags=["usuarios"])


@router.get("", response_model=list[UsuarioOut])
def listar(db: Session = Depends(get_db), _: Usuario = Depends(requiere_rol("admin"))):
    return db.execute(select(Usuario).order_by(Usuario.nombre)).scalars().all()


@router.post("", response_model=UsuarioOut)
def crear(datos: UsuarioCrear, db: Session = Depends(get_db),
          _: Usuario = Depends(requiere_rol("admin"))):
    email = datos.email.lower()
    if db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none():
        raise HTTPException(400, "Ya existe un usuario con ese correo")
    usuario = Usuario(
        email=email,
        nombre=datos.nombre,
        rol=datos.rol,
        area_id=datos.area_id,
        hash_clave=hash_clave(datos.clave),
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def actualizar(usuario_id: int, datos: UsuarioActualizar, db: Session = Depends(get_db),
               _: Usuario = Depends(requiere_rol("admin"))):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(404, "Usuario no encontrado")
    if datos.nombre is not None:
        usuario.nombre = datos.nombre
    if datos.rol is not None:
        usuario.rol = datos.rol
    if datos.area_id is not None:
        usuario.area_id = datos.area_id
    if datos.activo is not None:
        usuario.activo = datos.activo
    if datos.clave:
        usuario.hash_clave = hash_clave(datos.clave)
    db.commit()
    db.refresh(usuario)
    return usuario
