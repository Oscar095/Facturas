"""Gestión de roles y sus permisos (solo quien tiene permiso de administrar).

Los roles de sistema (admin, contabilidad, area) son de solo lectura: editarlos
podría cambiar el comportamiento histórico o dejar al administrador sin acceso.
Un rol solo se puede eliminar si ningún usuario lo tiene asignado.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Rol, Usuario
from ..schemas import RolActualizar, RolBase, RolOut
from ..security import requiere_permiso

router = APIRouter(prefix="/api/roles", tags=["roles"])

_NOMBRE_VALIDO = re.compile(r"^[a-z0-9áéíóúñü_-]{2,20}$")


def _con_uso(db: Session, roles: list[Rol]) -> list[RolOut]:
    conteos = dict(db.execute(select(Usuario.rol, func.count()).group_by(Usuario.rol)).all())
    salida = []
    for r in roles:
        item = RolOut.model_validate(r)
        item.en_uso = conteos.get(r.nombre, 0)
        salida.append(item)
    return salida


@router.get("", response_model=list[RolOut])
def listar(db: Session = Depends(get_db),
           _: Usuario = Depends(requiere_permiso("administrar"))):
    roles = db.execute(
        select(Rol).order_by(Rol.es_sistema.desc(), Rol.nombre)
    ).scalars().all()
    return _con_uso(db, roles)


@router.post("", response_model=RolOut)
def crear(datos: RolBase, db: Session = Depends(get_db),
          _: Usuario = Depends(requiere_permiso("administrar"))):
    nombre = datos.nombre.strip().lower()
    if not _NOMBRE_VALIDO.match(nombre):
        raise HTTPException(
            400, "Nombre inválido: 2 a 20 caracteres en minúsculas, números, '-' o '_' (sin espacios)")
    if db.execute(select(Rol).where(Rol.nombre == nombre)).scalar_one_or_none():
        raise HTTPException(400, "Ya existe un rol con ese nombre")
    rol = Rol(
        nombre=nombre,
        descripcion=(datos.descripcion or "").strip() or None,
        ver_todas_areas=datos.ver_todas_areas,
        editar_facturas=datos.editar_facturas,
        aprobar=datos.aprobar,
        contabilizar=datos.contabilizar,
        administrar=datos.administrar,
        es_sistema=False,
    )
    db.add(rol)
    db.commit()
    db.refresh(rol)
    return _con_uso(db, [rol])[0]


@router.patch("/{rol_id}", response_model=RolOut)
def actualizar(rol_id: int, datos: RolActualizar, db: Session = Depends(get_db),
               _: Usuario = Depends(requiere_permiso("administrar"))):
    rol = db.get(Rol, rol_id)
    if rol is None:
        raise HTTPException(404, "Rol no encontrado")
    if rol.es_sistema:
        raise HTTPException(400, "Los roles de sistema no se pueden modificar")
    cambios = datos.model_dump(exclude_unset=True)
    if "descripcion" in cambios:
        cambios["descripcion"] = (cambios["descripcion"] or "").strip() or None
    for campo, valor in cambios.items():
        setattr(rol, campo, valor)
    db.commit()
    db.refresh(rol)
    return _con_uso(db, [rol])[0]


@router.delete("/{rol_id}")
def eliminar(rol_id: int, db: Session = Depends(get_db),
             _: Usuario = Depends(requiere_permiso("administrar"))):
    rol = db.get(Rol, rol_id)
    if rol is None:
        raise HTTPException(404, "Rol no encontrado")
    if rol.es_sistema:
        raise HTTPException(400, "Los roles de sistema no se pueden eliminar")
    en_uso = db.scalar(select(func.count()).where(Usuario.rol == rol.nombre).select_from(Usuario))
    if en_uso:
        raise HTTPException(400, f"No se puede eliminar: {en_uso} usuario(s) tienen este rol")
    db.delete(rol)
    db.commit()
    return {"ok": True}
