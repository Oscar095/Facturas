"""Firmas digitales del usuario — estrictamente privadas.

Cada endpoint opera SOLO sobre las firmas del usuario autenticado: toda consulta
filtra por usuario_id y una firma ajena responde 404 (no 403, para no revelar
que existe). No hay excepción para el rol admin: nadie ve ni usa firmas de otros.
"""
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Firma, Usuario
from ..schemas import FirmaOut
from ..security import usuario_actual
from ..services.blob_storage import get_almacen

router = APIRouter(prefix="/api/firmas", tags=["firmas"])

# Solo imágenes; PNG con fondo transparente es lo ideal para estampar en PDF
_EXTENSIONES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def _firma_propia(db: Session, firma_id: int, usuario: Usuario) -> Firma:
    firma = db.execute(
        select(Firma).where(Firma.id == firma_id, Firma.usuario_id == usuario.id)
    ).scalar_one_or_none()
    if firma is None:
        raise HTTPException(404, "Firma no encontrada")
    return firma


@router.get("", response_model=list[FirmaOut])
def mis_firmas(db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    return db.execute(
        select(Firma).where(Firma.usuario_id == usuario.id).order_by(Firma.creado_en.desc())
    ).scalars().all()


@router.post("", response_model=FirmaOut)
def subir_firma(
    archivo: UploadFile = File(...),
    nombre: str = Form(""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    ext = (archivo.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in _EXTENSIONES:
        raise HTTPException(400, f"Formato inválido. Usa imagen: {', '.join(sorted(_EXTENSIONES))}")

    datos = archivo.file.read()
    if not datos:
        raise HTTPException(400, "Archivo vacío")
    if len(datos) > _MAX_BYTES:
        raise HTTPException(400, "La imagen supera el máximo de 2 MB")

    # ruta no adivinable y aislada por usuario
    base = re.sub(r"[^A-Za-z0-9._-]", "_", archivo.filename or f"firma.{ext}")[:120]
    ruta = f"firmas/{usuario.id}/{uuid.uuid4().hex}_{base}"
    get_almacen().subir(ruta, datos, content_type=_EXTENSIONES[ext])

    firma = Firma(
        usuario_id=usuario.id,
        nombre=(nombre or "").strip() or "Firma",
        blob_path=ruta,
        nombre_archivo=archivo.filename or f"firma.{ext}",
    )
    db.add(firma)
    db.commit()
    db.refresh(firma)
    return firma


@router.get("/{firma_id}/imagen")
def imagen_firma(firma_id: int, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(usuario_actual)):
    firma = _firma_propia(db, firma_id, usuario)
    datos = get_almacen().descargar(firma.blob_path)
    ext = firma.blob_path.rsplit(".", 1)[-1].lower()
    return Response(
        datos,
        media_type=_EXTENSIONES.get(ext, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{firma.nombre_archivo}"',
                 # imagen privada: que ningún proxy/navegador compartido la cachee
                 "Cache-Control": "private, no-store"},
    )


@router.delete("/{firma_id}")
def eliminar_firma(firma_id: int, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(usuario_actual)):
    firma = _firma_propia(db, firma_id, usuario)
    # la firma es dato personal: se borra también el archivo del Blob
    get_almacen().eliminar(firma.blob_path)
    db.delete(firma)
    db.commit()
    return {"ok": True}
