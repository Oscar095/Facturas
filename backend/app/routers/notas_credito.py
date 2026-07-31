"""Notas crédito extraídas del portal Siesa — módulo de solo consulta.

Visible para quien tenga el permiso `ver_todas_areas` (las notas crédito no
tienen área asignada, así que no hay filtrado por fila: es todo o nada).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import NotaCredito, Proveedor, Usuario
from ..schemas import PaginaNotasCredito
from ..security import requiere_permiso
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/notas-credito", tags=["notas_credito"])


@router.get("", response_model=PaginaNotasCredito)
def listar(
    db: Session = Depends(get_db),
    _: Usuario = Depends(requiere_permiso("ver_todas_areas")),
    proveedor: str | None = Query(None, description="texto en NIT o razón social"),
    pagina: int = 1,
    por_pagina: int = Query(25, le=200),
):
    q = select(NotaCredito).options(joinedload(NotaCredito.proveedor))
    if proveedor:
        like = f"%{proveedor}%"
        q = q.join(NotaCredito.proveedor).where(
            Proveedor.nit.like(like) | Proveedor.razon_social.like(like)
        )
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    q = q.order_by(
        NotaCredito.fecha_emision.desc(), NotaCredito.fecha_recepcion.desc(), NotaCredito.id.desc()
    ).offset((pagina - 1) * por_pagina).limit(por_pagina)
    items = db.execute(q).unique().scalars().all()
    return PaginaNotasCredito(items=items, total=total or 0, pagina=pagina, por_pagina=por_pagina)


@router.get("/{nota_id}/pdf")
def descargar_pdf(nota_id: int, db: Session = Depends(get_db),
                  _: Usuario = Depends(requiere_permiso("ver_todas_areas"))):
    nota = db.get(NotaCredito, nota_id)
    if nota is None:
        raise HTTPException(404, "Nota crédito no encontrada")
    if not nota.blob_pdf:
        raise HTTPException(404, "La nota crédito no tiene PDF")
    # Proxy de bytes desde el backend (nunca redirect/SAS: Blob no tiene CORS)
    datos = get_almacen().descargar(nota.blob_pdf)
    return Response(datos, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nota.numero}.pdf"'})
