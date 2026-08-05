"""Notas crédito extraídas del portal Siesa.

Módulo de consulta + asignación de área: una nota crédito NO pasa por el flujo
de completitud/aprobación/contabilización de las facturas, pero sí se le asigna
un área responsable (con las mismas `reglas_area`, sin IA) para saber a quién
corresponde el crédito.

Alcance por rol igual que en facturas: con `ver_todas_areas` se ven todas; sin
ese permiso, el usuario solo ve las de su área (las que quedaron sin asignar
solo las ve quien ve todas, y puede asignarlas a mano).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import NotaCredito, Proveedor, Usuario
from ..schemas import NotaCreditoActualizar, NotaCreditoOut, PaginaNotasCredito
from ..security import requiere_permiso, tiene_permiso, usuario_actual
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/notas-credito", tags=["notas_credito"])


def _filtrar_por_rol(query, usuario: Usuario, db: Session):
    """Sin el permiso 'ver_todas_areas', el usuario solo ve notas de su área."""
    if not tiene_permiso(db, usuario, "ver_todas_areas"):
        if usuario.area_id is None:
            return query.where(NotaCredito.id == -1)  # sin área => no ve nada
        return query.where(NotaCredito.area_id == usuario.area_id)
    return query


@router.get("", response_model=PaginaNotasCredito)
def listar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
    proveedor: str | None = Query(None, description="texto en NIT o razón social"),
    area_id: int | None = None,
    sin_area: bool = Query(False, description="solo las que no tienen área asignada"),
    pagina: int = 1,
    por_pagina: int = Query(25, le=200),
):
    q = select(NotaCredito).options(
        joinedload(NotaCredito.proveedor),
        joinedload(NotaCredito.area),
        joinedload(NotaCredito.responsable),
    )
    q = _filtrar_por_rol(q, usuario, db)
    if proveedor:
        like = f"%{proveedor}%"
        q = q.join(NotaCredito.proveedor).where(
            Proveedor.nit.like(like) | Proveedor.razon_social.like(like)
        )
    if area_id:
        q = q.where(NotaCredito.area_id == area_id)
    if sin_area:
        q = q.where(NotaCredito.area_id.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    q = q.order_by(
        NotaCredito.fecha_emision.desc(), NotaCredito.fecha_recepcion.desc(), NotaCredito.id.desc()
    ).offset((pagina - 1) * por_pagina).limit(por_pagina)
    items = db.execute(q).unique().scalars().all()
    return PaginaNotasCredito(items=items, total=total or 0, pagina=pagina, por_pagina=por_pagina)


def _cargar_nota(db: Session, nota_id: int, usuario: Usuario) -> NotaCredito:
    nota = db.get(NotaCredito, nota_id)
    if nota is None:
        raise HTTPException(404, "Nota crédito no encontrada")
    if not tiene_permiso(db, usuario, "ver_todas_areas") and nota.area_id != usuario.area_id:
        raise HTTPException(403, "No autorizado para ver esta nota crédito")
    return nota


@router.patch("/{nota_id}", response_model=NotaCreditoOut)
def actualizar(nota_id: int, datos: NotaCreditoActualizar,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(requiere_permiso("editar_facturas"))):
    """Asignación manual de área/responsable (mismo permiso que editar facturas)."""
    nota = _cargar_nota(db, nota_id, usuario)
    if datos.area_id is not None:
        nota.area_id = datos.area_id
    if datos.responsable_id is not None:
        nota.responsable_id = datos.responsable_id
    db.commit()
    db.refresh(nota)
    return nota


@router.get("/{nota_id}/pdf")
def descargar_pdf(nota_id: int, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(usuario_actual)):
    nota = _cargar_nota(db, nota_id, usuario)
    if not nota.blob_pdf:
        raise HTTPException(404, "La nota crédito no tiene PDF")
    # Proxy de bytes desde el backend (nunca redirect/SAS: Blob no tiene CORS)
    datos = get_almacen().descargar(nota.blob_pdf)
    return Response(datos, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nota.numero}.pdf"'})
