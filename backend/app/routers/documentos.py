from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Documento, Evento, Factura, TIPOS_DOCUMENTO, Usuario
from ..schemas import FacturaDetalle
from ..security import usuario_actual
from ..services import reglas
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/documentos", tags=["documentos"])

# Tipos que un usuario puede adjuntar (la FV la carga el robot)
TIPOS_CARGABLES = {"OCN", "OCS", "CRN", "OTRO"}


@router.post("/{factura_id}", response_model=FacturaDetalle)
def subir_documento(
    factura_id: int,
    tipo: str = Form(...),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    tipo = tipo.upper()
    if tipo not in TIPOS_CARGABLES:
        raise HTTPException(400, f"Tipo inválido. Permitidos: {sorted(TIPOS_CARGABLES)}")

    factura = db.get(Factura, factura_id)
    if factura is None:
        raise HTTPException(404, "Factura no encontrada")
    if usuario.rol == "area" and factura.area_id != usuario.area_id:
        raise HTTPException(403, "No autorizado para cargar en esta factura")

    datos = archivo.file.read()
    if not datos:
        raise HTTPException(400, "Archivo vacío")

    ext = (archivo.filename or "").rsplit(".", 1)[-1].lower() or "bin"
    ruta = f"documentos/{factura_id}/{tipo}_{factura.numero}.{ext}"
    get_almacen().subir(ruta, datos, content_type=archivo.content_type)

    db.add(Documento(
        factura_id=factura.id,
        tipo=tipo,
        blob_path=ruta,
        nombre_archivo=archivo.filename or f"{tipo}.{ext}",
        subido_por_id=usuario.id,
    ))
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="carga_documento",
                  detalle=f"{tipo}: {archivo.filename}"))
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.commit()
    db.refresh(factura)

    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = reglas.faltan_documentos(db, factura)
    return salida


@router.delete("/{documento_id}", response_model=FacturaDetalle)
def eliminar_documento(documento_id: int, db: Session = Depends(get_db),
                       usuario: Usuario = Depends(usuario_actual)):
    doc = db.get(Documento, documento_id)
    if doc is None:
        raise HTTPException(404, "Documento no encontrado")
    if doc.tipo == "FV":
        raise HTTPException(400, "La factura de venta no se puede eliminar")
    factura = db.get(Factura, doc.factura_id)
    if usuario.rol == "area" and factura.area_id != usuario.area_id:
        raise HTTPException(403, "No autorizado")
    db.delete(doc)
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="elimina_documento",
                  detalle=f"{doc.tipo}: {doc.nombre_archivo}"))
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.commit()
    db.refresh(factura)
    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = reglas.faltan_documentos(db, factura)
    return salida
