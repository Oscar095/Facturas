"""Endpoints del panel (con JWT): resumen por estado y log del robot."""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..ingesta.sincronizar import sincronizar
from ..models import Ejecucion, Factura, Usuario
from ..schemas import EjecucionOut
from ..security import requiere_rol, usuario_actual

router = APIRouter(prefix="/api/panel", tags=["panel"])


def _correr_sync_en_fondo(dias: int):
    db = SessionLocal()
    try:
        sincronizar(db, dias=dias)
    finally:
        db.close()


@router.get("/resumen")
def resumen(db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    """Conteo de facturas por estado (respetando el alcance del rol de área)."""
    q = select(Factura.estado_proceso, func.count()).group_by(Factura.estado_proceso)
    if usuario.rol == "area" and usuario.area_id is not None:
        q = q.where(Factura.area_id == usuario.area_id)
    conteos = {estado: n for estado, n in db.execute(q).all()}
    orden = ["nueva", "asignada", "docs_pendientes", "lista_contabilizar", "contabilizada"]
    return {
        "por_estado": {e: conteos.get(e, 0) for e in orden},
        "total": sum(conteos.values()),
    }


@router.get("/ejecuciones", response_model=list[EjecucionOut])
def ejecuciones(limite: int = 20, db: Session = Depends(get_db),
                _: Usuario = Depends(requiere_rol("admin", "contabilidad"))):
    return db.execute(
        select(Ejecucion).order_by(Ejecucion.inicio.desc()).limit(limite)
    ).scalars().all()


@router.post("/sincronizar")
def sincronizar_ahora(background: BackgroundTasks, dias: int = 3,
                      _: Usuario = Depends(requiere_rol("admin"))):
    """Dispara la ingesta manualmente desde el portal (solo admin).

    Corre en segundo plano (puede tardar varios minutos); el resultado se
    consulta en /api/panel/ejecuciones una vez termine.
    """
    background.add_task(_correr_sync_en_fondo, dias)
    return {"ok": True, "mensaje": "Sincronización iniciada. Revisa el log en unos minutos."}
