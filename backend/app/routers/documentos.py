import re
import uuid
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Documento, Evento, Factura, TIPOS_DOCUMENTO, Usuario
from ..schemas import FacturaDetalle
from ..security import tiene_permiso, usuario_actual
from ..services import reglas
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/documentos", tags=["documentos"])

# Tipos que un usuario puede adjuntar (la FV la carga el robot)
TIPOS_CARGABLES = {"OCN", "OCS", "CRN", "OTRO"}


def _nombre_seguro(nombre: str) -> str:
    """Nombre apto para ruta de Blob, conservando la extensión (la firma decide
    por ella qué documentos son PDF)."""
    base = PurePath(nombre.replace("\\", "/")).name  # algunos navegadores mandan la ruta
    limpio = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "archivo"
    return limpio[-120:]  # el recorte va por el inicio: la extensión queda


def ruta_documento(factura_id: int, tipo: str, nombre_archivo: str) -> str:
    """Ruta ÚNICA en el Blob para un documento adjunto.

    Antes era `documentos/{factura}/{tipo}_{numero}.{ext}`: dos archivos del mismo
    tipo en la misma factura (tres soportes "Otro", dos fotos) caían en la MISMA
    ruta, cada subida pisaba a la anterior y todas las filas terminaban abriendo el
    último archivo. Así quedaron 43 documentos reales abriendo el archivo de otro
    (34 se perdieron sin remedio; ver CLAUDE.md). El UUID hace la ruta
    irrepetible; el nombre original va detrás solo para que el Blob sea legible.
    Mismo patrón que `routers/firmas.py`.
    """
    return f"documentos/{factura_id}/{tipo}_{uuid.uuid4().hex[:12]}_{_nombre_seguro(nombre_archivo)}"


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
    if not tiene_permiso(db, usuario, "ver_todas_areas") and factura.area_id != usuario.area_id:
        raise HTTPException(403, "No autorizado para cargar en esta factura")

    datos = archivo.file.read()
    if not datos:
        raise HTTPException(400, "Archivo vacío")

    # Se acepta CUALQUIER tipo de archivo (soportes, fotos, Excel, correos .msg):
    # la firma al aprobar solo se estampa en los PDF y omite el resto.
    nombre = PurePath((archivo.filename or "").replace("\\", "/")).name or f"{tipo}.bin"
    ruta = ruta_documento(factura_id, tipo, nombre)
    # sobrescribir=False: un adjunto nunca debe destruir otro archivo, aunque
    # alguien vuelva a construir una ruta repetible por error.
    get_almacen().subir(ruta, datos, content_type=archivo.content_type, sobrescribir=False)

    db.add(Documento(
        factura_id=factura.id,
        tipo=tipo,
        blob_path=ruta,
        nombre_archivo=nombre,
        subido_por_id=usuario.id,
    ))
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="carga_documento",
                  detalle=f"{tipo}: {nombre}"))
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
    if not tiene_permiso(db, usuario, "ver_todas_areas") and factura.area_id != usuario.area_id:
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
