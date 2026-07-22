import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Documento, Evento, Factura, Proveedor, Usuario
from ..schemas import FacturaActualizar, FacturaDetalle, FacturaResumen, PaginaFacturas
from ..security import requiere_rol, usuario_actual
from ..services import reglas
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/facturas", tags=["facturas"])


def _filtrar_por_rol(query, usuario: Usuario):
    """Los usuarios de área solo ven las facturas de su área; admin/contabilidad ven todo."""
    if usuario.rol == "area":
        if usuario.area_id is None:
            return query.where(Factura.id == -1)  # sin área => no ve nada
        return query.where(Factura.area_id == usuario.area_id)
    return query


@router.get("", response_model=PaginaFacturas)
def listar(
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
    estado: str | None = None,
    area_id: int | None = None,
    proveedor: str | None = Query(None, description="texto en NIT o razón social"),
    solo_mias: bool = False,
    pagina: int = 1,
    por_pagina: int = Query(25, le=200),
):
    q = select(Factura).options(
        joinedload(Factura.proveedor),
        joinedload(Factura.area),
        joinedload(Factura.responsable),
    )
    q = _filtrar_por_rol(q, usuario)
    if estado:
        q = q.where(Factura.estado_proceso == estado)
    if area_id:
        q = q.where(Factura.area_id == area_id)
    if solo_mias:
        q = q.where(Factura.responsable_id == usuario.id)
    if proveedor:
        like = f"%{proveedor}%"
        q = q.join(Factura.proveedor).where(
            Proveedor.nit.like(like) | Proveedor.razon_social.like(like)
        )

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    q = q.order_by(Factura.fecha_recepcion.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina)
    items = db.execute(q).unique().scalars().all()
    return PaginaFacturas(items=items, total=total or 0, pagina=pagina, por_pagina=por_pagina)


def _cargar_factura(db: Session, factura_id: int, usuario: Usuario) -> Factura:
    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if usuario.rol == "area" and factura.area_id != usuario.area_id:
        raise HTTPException(403, "No autorizado para ver esta factura")
    return factura


@router.get("/{factura_id}", response_model=FacturaDetalle)
def detalle(factura_id: int, db: Session = Depends(get_db),
            usuario: Usuario = Depends(usuario_actual)):
    factura = _cargar_factura(db, factura_id, usuario)
    faltantes = reglas.faltan_documentos(db, factura)
    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = faltantes
    return salida


@router.get("/{factura_id}/pdf")
def descargar_pdf(factura_id: int, db: Session = Depends(get_db),
                  usuario: Usuario = Depends(usuario_actual)):
    factura = _cargar_factura(db, factura_id, usuario)
    if not factura.blob_pdf:
        raise HTTPException(404, "La factura no tiene PDF")
    # Se sirve el archivo desde el backend (no se redirige a una URL con SAS de
    # Azure Blob): el frontend adjunta el token JWT vía fetch() y una redirección
    # cross-origin hacia blob.core.windows.net queda bloqueada por CORS al no
    # estar habilitado en la cuenta de almacenamiento.
    datos = get_almacen().descargar(factura.blob_pdf)
    return Response(datos, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{factura.numero}.pdf"'})


@router.get("/documento/{documento_id}/archivo")
def descargar_documento(documento_id: int, db: Session = Depends(get_db),
                        usuario: Usuario = Depends(usuario_actual)):
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(404, "Documento no encontrado")
    _cargar_factura(db, doc.factura_id, usuario)
    datos = get_almacen().descargar(doc.blob_path)
    content_type = mimetypes.guess_type(doc.nombre_archivo)[0] or "application/octet-stream"
    return Response(datos, media_type=content_type,
                    headers={"Content-Disposition": f'inline; filename="{doc.nombre_archivo}"'})


@router.patch("/{factura_id}", response_model=FacturaDetalle)
def actualizar(factura_id: int, datos: FacturaActualizar,
               db: Session = Depends(get_db),
               usuario: Usuario = Depends(requiere_rol("admin", "contabilidad"))):
    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if datos.tipo_orden is not None:
        factura.tipo_orden = datos.tipo_orden
    if datos.area_id is not None:
        factura.area_id = datos.area_id
    if datos.responsable_id is not None:
        factura.responsable_id = datos.responsable_id
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="actualizacion",
                  detalle=datos.model_dump_json()))
    reglas.evaluar_completitud(db, factura)
    db.commit()
    db.refresh(factura)
    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = reglas.faltan_documentos(db, factura)
    return salida


@router.post("/{factura_id}/contabilizar", response_model=FacturaDetalle)
def contabilizar(factura_id: int, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(requiere_rol("admin", "contabilidad"))):
    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if factura.estado_proceso != "lista_contabilizar":
        faltan = reglas.faltan_documentos(db, factura)
        raise HTTPException(400, f"La factura no está lista. Faltan documentos: {faltan}")
    factura.estado_proceso = "contabilizada"
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="contabilizada"))
    db.commit()
    db.refresh(factura)
    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = []
    return salida
