import mimetypes
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import Documento, Evento, Factura, Firma, Proveedor, Usuario
from ..schemas import (
    AprobarIn,
    AprobarLoteIn,
    FacturaActualizar,
    FacturaDetalle,
    FacturaResumen,
    ObservacionesIn,
    PaginaFacturas,
    ResultadoAprobacion,
    ResumenAprobacionLote,
)
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
    tipo_documento: str | None = Query(None, description="FACTURA | EQUIVALENTE"),
    fecha_desde: date | None = Query(None, description="emisión desde (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(None, description="emisión hasta (YYYY-MM-DD, inclusive)"),
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
    if tipo_documento:
        q = q.where(Factura.tipo_documento == tipo_documento)
    # El rango filtra por fecha_emision: se guarda tal cual la entrega el portal
    # (hora local de Colombia), así que se compara directo, sin ajuste de huso
    # horario — a diferencia de fecha_recepcion (UTC), que sí lo necesitaría.
    if fecha_desde:
        q = q.where(Factura.fecha_emision >= fecha_desde)
    if fecha_hasta:
        # < día siguiente para que "hasta" incluya el día completo con cualquier hora
        q = q.where(Factura.fecha_emision < fecha_hasta + timedelta(days=1))
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


@router.put("/{factura_id}/observaciones", response_model=FacturaDetalle)
def guardar_observaciones(factura_id: int, datos: ObservacionesIn,
                          db: Session = Depends(get_db),
                          usuario: Usuario = Depends(usuario_actual)):
    """Nota libre para el jefe que aprueba (por qué falta un documento, etc.).

    Deliberadamente NO exige el permiso `editar_facturas` (que sí protege área,
    tipo de orden y responsable): la escribe quien carga los documentos, que
    solo necesita acceso al área de la factura — el mismo criterio de
    `routers/documentos.py`.
    """
    factura = _cargar_factura(db, factura_id, usuario)
    texto = (datos.observaciones or "").strip()
    factura.observaciones = texto or None
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="observaciones",
                  detalle=texto[:500] if texto else "observaciones borradas"))
    db.commit()
    db.refresh(factura)
    return _responder_detalle(db, factura)


# Tope del lote: firmar es caro (bajar, sellar y subir cada PDF), así que se
# acota para que la petición no se eternice; la UI selecciona una página a la vez.
_MAX_LOTE = 100


def _texto_sello(usuario: Usuario) -> str:
    # hora local de Colombia (UTC-5) para el texto del sello
    fecha_local = datetime.utcnow() - timedelta(hours=5)
    return f"Aprobado por {usuario.nombre} — {fecha_local.strftime('%d/%m/%Y %H:%M')}"


def _detalle_aprobacion(usuario: Usuario, firma: Firma,
                        firmados: list[str], omitidos: list[str]) -> str:
    detalle = f"aprobada por {usuario.nombre} con la firma '{firma.nombre}'"
    if firmados:
        detalle += f" — documentos firmados: {', '.join(firmados)}"
    if omitidos:
        detalle += f" — sin firmar: {', '.join(omitidos)}"
    return detalle


def _sellar_documentos(db: Session, factura: Factura, almacen, imagen: bytes,
                       texto_sello: str) -> tuple[list[str], list[str]]:
    """Estampa la firma en TODOS los documentos PDF de la factura, sin importar
    su tipo. Devuelve (firmados, omitidos); los no-PDF se omiten.

    El sellado se sube como blob nuevo (`*_firmado.pdf`) y el original queda
    intacto por trazabilidad. Lanza RuntimeError si un PDF no se puede sellar:
    dejar la factura firmada a medias sería peor que no aprobarla.
    """
    documentos = db.execute(
        select(Documento).where(Documento.factura_id == factura.id)
    ).scalars().all()
    firmados: list[str] = []
    omitidos: list[str] = []
    for doc in documentos:
        if not doc.blob_path.lower().endswith(".pdf"):
            omitidos.append(f"{doc.tipo} (no es PDF)")
            continue
        try:
            sellado = estampar_firma(almacen.descargar(doc.blob_path), imagen, texto_sello)
        except Exception as e:  # noqa: BLE001 — un PDF ilegible no debe aprobar a medias
            raise RuntimeError(
                f"No se pudo firmar el documento {doc.tipo} ({doc.nombre_archivo}): {e}"
            )
        base, ext = doc.blob_path.rsplit(".", 1)
        nueva_ruta = f"{base}_firmado.{ext}"
        almacen.subir(nueva_ruta, sellado, content_type="application/pdf")
        if factura.blob_pdf == doc.blob_path:  # la FV comparte ruta con factura.blob_pdf
            factura.blob_pdf = nueva_ruta
        doc.blob_path = nueva_ruta
        firmados.append(doc.tipo)
    return firmados, omitidos


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


@router.post("/{factura_id}/aprobar", response_model=FacturaDetalle)
def aprobar(factura_id: int, datos: AprobarIn, db: Session = Depends(get_db),
            usuario: Usuario = Depends(usuario_actual)):
    """Aprueba una factura procesada estampando la firma del usuario en TODOS
    los documentos PDF adjuntos, sin importar su tipo, en todas las páginas de
    cada documento, abajo a la derecha.

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
    try:
        firmados, omitidos = _sellar_documentos(
            db, factura, almacen, imagen, _texto_sello(usuario)
        )
    except RuntimeError as e:
        raise HTTPException(422, str(e))

    factura.estado_proceso = "aprobada"
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="aprobada",
                  detalle=_detalle_aprobacion(usuario, firma, firmados, omitidos)))
    db.commit()
    db.refresh(factura)
    return _responder_detalle(db, factura)


@router.post("/aprobar-lote", response_model=ResumenAprobacionLote)
def aprobar_lote(datos: AprobarLoteIn, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(usuario_actual)):
    """Aprueba y firma VARIAS facturas de una vez desde el listado.

    Pensado para el jefe de área que ya revisó las facturas en la tabla y no
    necesita entrar una por una. Las que aún no están 'procesada' se procesan
    en el mismo paso — seleccionarlas ES la declaración humana de que sus
    documentos bastan, igual que el botón Procesar del detalle.

    Cada factura se confirma por separado: si una falla (PDF ilegible, por
    ejemplo) se revierte SOLO esa y el lote continúa. La respuesta detalla qué
    pasó con cada una para que la UI lo muestre.
    """
    if not tiene_permiso(db, usuario, "aprobar"):
        raise HTTPException(403, "Tu rol no tiene permiso para aprobar facturas")
    ids = list(dict.fromkeys(datos.ids))  # sin duplicados, conservando el orden
    if not ids:
        raise HTTPException(400, "No hay facturas seleccionadas")
    if len(ids) > _MAX_LOTE:
        raise HTTPException(400, f"Máximo {_MAX_LOTE} facturas por lote")

    # La firma se re-verifica como en la aprobación individual: nadie usa firmas
    # ajenas, ni siquiera un admin (404 para no revelar que existen).
    firma = db.execute(
        select(Firma).where(Firma.id == datos.firma_id, Firma.usuario_id == usuario.id)
    ).scalar_one_or_none()
    if firma is None:
        raise HTTPException(404, "Firma no encontrada")

    almacen = get_almacen()
    imagen = almacen.descargar(firma.blob_path)
    texto_sello = _texto_sello(usuario)
    ve_todas = tiene_permiso(db, usuario, "ver_todas_areas")

    resultados: list[ResultadoAprobacion] = []

    def omitir(factura_id: int, numero: str | None, motivo: str):
        resultados.append(ResultadoAprobacion(
            factura_id=factura_id, numero=numero, estado="omitida", detalle=motivo))

    for factura_id in ids:
        factura = db.get(Factura, factura_id)
        if factura is None:
            omitir(factura_id, None, "no encontrada")
            continue
        if not ve_todas and factura.area_id != usuario.area_id:
            omitir(factura_id, factura.numero, "no pertenece a tu área")
            continue
        if factura.estado_proceso in ("aprobada", "contabilizada"):
            omitir(factura_id, factura.numero, f"ya está {factura.estado_proceso}")
            continue
        if factura.area_id is None:
            omitir(factura_id, factura.numero, "sin área asignada")
            continue

        try:
            if factura.estado_proceso != "procesada":
                faltantes = reglas.faltan_documentos(db, factura)
                factura.estado_proceso = "procesada"
                detalle_proc = "procesada en aprobación por lote"
                if faltantes:
                    detalle_proc += (
                        f" — con faltantes declarados como no requeridos: {', '.join(faltantes)}"
                    )
                db.add(Evento(factura_id=factura.id, usuario_id=usuario.id,
                              accion="procesada", detalle=detalle_proc))

            firmados, omitidos = _sellar_documentos(db, factura, almacen, imagen, texto_sello)
            factura.estado_proceso = "aprobada"
            db.add(Evento(
                factura_id=factura.id, usuario_id=usuario.id, accion="aprobada",
                detalle=_detalle_aprobacion(usuario, firma, firmados, omitidos)
                        + " — aprobación por lote",
            ))
            db.commit()
        except Exception as e:  # noqa: BLE001 — un fallo aislado no tumba el lote
            db.rollback()
            resultados.append(ResultadoAprobacion(
                factura_id=factura_id, numero=factura.numero, estado="error", detalle=str(e)))
            continue

        resultados.append(ResultadoAprobacion(
            factura_id=factura_id, numero=factura.numero, estado="aprobada",
            detalle=f"firmados: {', '.join(firmados)}" if firmados else "sin documentos PDF"))

    return ResumenAprobacionLote(
        aprobadas=sum(1 for r in resultados if r.estado == "aprobada"),
        omitidas=sum(1 for r in resultados if r.estado == "omitida"),
        errores=sum(1 for r in resultados if r.estado == "error"),
        resultados=resultados,
    )


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
