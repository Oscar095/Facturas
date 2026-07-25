import mimetypes
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Documento, Evento, Factura, Firma, Proveedor, Usuario
from ..schemas import AprobarIn, FacturaActualizar, FacturaDetalle, FacturaResumen, PaginaFacturas
from ..security import requiere_permiso, tiene_permiso, usuario_actual
from ..services import reglas
from ..services.blob_storage import get_almacen
from ..services.firmar_pdf import estampar_firma

router = APIRouter(prefix="/api/facturas", tags=["facturas"])


def _filtrar_por_rol(query, usuario: Usuario, db: Session):
    """Sin el permiso 'ver_todas_areas', el usuario solo ve facturas de su área."""
    if not tiene_permiso(db, usuario, "ver_todas_areas"):
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
    q = _filtrar_por_rol(q, usuario, db)
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
    # Más nuevas primero: por fecha de emisión de la factura (en SQL Server las
    # NULL quedan al final en DESC); desempate por fecha de carga y por id.
    q = q.order_by(
        Factura.fecha_emision.desc(), Factura.fecha_recepcion.desc(), Factura.id.desc()
    ).offset((pagina - 1) * por_pagina).limit(por_pagina)
    items = db.execute(q).unique().scalars().all()
    return PaginaFacturas(items=items, total=total or 0, pagina=pagina, por_pagina=por_pagina)


def _cargar_factura(db: Session, factura_id: int, usuario: Usuario) -> Factura:
    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if not tiene_permiso(db, usuario, "ver_todas_areas") and factura.area_id != usuario.area_id:
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
               usuario: Usuario = Depends(requiere_permiso("editar_facturas"))):
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


def _responder_detalle(db: Session, factura: Factura) -> FacturaDetalle:
    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = reglas.faltan_documentos(db, factura)
    return salida


@router.post("/{factura_id}/procesar", response_model=FacturaDetalle)
def procesar(factura_id: int, db: Session = Depends(get_db),
             usuario: Usuario = Depends(usuario_actual)):
    """El responsable declara que los documentos cargados son suficientes.

    Paso manual del flujo: hay facturas que no requieren todos los documentos
    de la regla estándar, así que quien procesa asume la completitud aunque
    haya faltantes. Al quedar 'procesada' se habilita el botón de aprobar.
    """
    factura = _cargar_factura(db, factura_id, usuario)
    if not tiene_permiso(db, usuario, "aprobar"):
        raise HTTPException(403, "Tu rol no tiene permiso para procesar facturas")
    if factura.estado_proceso in ("procesada", "aprobada", "contabilizada"):
        raise HTTPException(400, f"La factura ya está {factura.estado_proceso}")
    if factura.area_id is None:
        raise HTTPException(400, "Asigna un área a la factura antes de procesarla")

    faltantes = reglas.faltan_documentos(db, factura)
    factura.estado_proceso = "procesada"
    detalle_evento = (
        f"con faltantes declarados como no requeridos: {', '.join(faltantes)}"
        if faltantes else "todos los documentos completos"
    )
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="procesada",
                  detalle=detalle_evento))
    db.commit()
    db.refresh(factura)
    return _responder_detalle(db, factura)


# Documentos que se sellan al aprobar (OTRO queda por fuera a propósito)
TIPOS_FIRMABLES = ("FV", "OCN", "OCS", "CRN")


@router.post("/{factura_id}/aprobar", response_model=FacturaDetalle)
def aprobar(factura_id: int, datos: AprobarIn, db: Session = Depends(get_db),
            usuario: Usuario = Depends(usuario_actual)):
    """Aprueba una factura procesada estampando la firma del usuario en todos
    los documentos PDF adjuntos (FV/OCN/OCS/CRN), en TODAS las páginas de cada
    documento, abajo a la derecha.

    La firma debe pertenecer al usuario que aprueba (se re-verifica aquí: nadie
    usa firmas ajenas). El sellado se sube como blob nuevo (`*_firmado.pdf`);
    el original queda intacto en el almacenamiento por trazabilidad.
    """
    factura = _cargar_factura(db, factura_id, usuario)
    if not tiene_permiso(db, usuario, "aprobar"):
        raise HTTPException(403, "Tu rol no tiene permiso para aprobar facturas")
    if factura.estado_proceso != "procesada":
        raise HTTPException(400, "Solo se puede aprobar una factura procesada")

    firma = db.execute(
        select(Firma).where(Firma.id == datos.firma_id, Firma.usuario_id == usuario.id)
    ).scalar_one_or_none()
    if firma is None:
        raise HTTPException(404, "Firma no encontrada")

    almacen = get_almacen()
    imagen = almacen.descargar(firma.blob_path)
    # hora local de Colombia (UTC-5) para el texto del sello
    fecha_local = datetime.utcnow() - timedelta(hours=5)
    texto_sello = f"Aprobado por {usuario.nombre} — {fecha_local.strftime('%d/%m/%Y %H:%M')}"

    documentos = db.execute(
        select(Documento).where(Documento.factura_id == factura.id)
    ).scalars().all()
    firmados: list[str] = []
    omitidos: list[str] = []
    for doc in documentos:
        if doc.tipo not in TIPOS_FIRMABLES:
            continue
        if not doc.blob_path.lower().endswith(".pdf"):
            omitidos.append(f"{doc.tipo} (no es PDF)")
            continue
        try:
            sellado = estampar_firma(almacen.descargar(doc.blob_path), imagen, texto_sello)
        except Exception as e:  # noqa: BLE001 — un PDF ilegible no debe aprobar a medias
            raise HTTPException(
                422, f"No se pudo firmar el documento {doc.tipo} ({doc.nombre_archivo}): {e}"
            )
        base, ext = doc.blob_path.rsplit(".", 1)
        nueva_ruta = f"{base}_firmado.{ext}"
        almacen.subir(nueva_ruta, sellado, content_type="application/pdf")
        if factura.blob_pdf == doc.blob_path:  # la FV comparte ruta con factura.blob_pdf
            factura.blob_pdf = nueva_ruta
        doc.blob_path = nueva_ruta
        firmados.append(doc.tipo)

    factura.estado_proceso = "aprobada"
    detalle = f"aprobada por {usuario.nombre} con la firma '{firma.nombre}'"
    if firmados:
        detalle += f" — documentos firmados: {', '.join(firmados)}"
    if omitidos:
        detalle += f" — sin firmar: {', '.join(omitidos)}"
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="aprobada",
                  detalle=detalle))
    db.commit()
    db.refresh(factura)
    return _responder_detalle(db, factura)


@router.post("/{factura_id}/contabilizar", response_model=FacturaDetalle)
def contabilizar(factura_id: int, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(requiere_permiso("contabilizar"))):
    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if factura.estado_proceso != "aprobada":
        raise HTTPException(400, "La factura debe estar aprobada antes de contabilizarla")
    factura.estado_proceso = "contabilizada"
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="contabilizada"))
    db.commit()
    db.refresh(factura)
    return _responder_detalle(db, factura)
