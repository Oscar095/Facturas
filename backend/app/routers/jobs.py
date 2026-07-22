"""Endpoints para el robot de ingesta, protegidos por API key (los llama n8n)."""
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..ingesta.sincronizar import sincronizar
from ..models import Ejecucion
from ..schemas import EjecucionOut, ResumenSync
from ..security import verificar_api_key

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _correr_sync(dias: int, desde: str | None, hasta: str | None):
    db = SessionLocal()
    try:
        sincronizar(db, dias=dias, fecha_desde=desde, fecha_hasta=hasta)
    finally:
        db.close()


@router.post("/sync", response_model=ResumenSync)
def lanzar_sync(
    background: BackgroundTasks,
    dias: int = 3,
    desde: str | None = None,
    hasta: str | None = None,
    esperar: bool = False,
    x_api_key: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """Dispara la ingesta. Por defecto responde de inmediato (async) con la
    ejecución en curso; si `esperar=true`, corre síncrono y devuelve el resumen final.
    """
    verificar_api_key(x_api_key)
    if esperar:
        resumen = sincronizar(db, dias=dias, fecha_desde=desde, fecha_hasta=hasta)
        return ResumenSync(**{k: resumen[k] for k in
                              ("ejecucion_id", "estado", "facturas_nuevas",
                               "errores", "sin_area_asignada")})
    background.add_task(_correr_sync, dias, desde, hasta)
    return ResumenSync(ejecucion_id=0, estado="en_curso", facturas_nuevas=0,
                       errores=0, sin_area_asignada=[])


@router.get("/{ejecucion_id}", response_model=EjecucionOut)
def estado_ejecucion(ejecucion_id: int, db: Session = Depends(get_db),
                     x_api_key: str | None = Header(None)):
    verificar_api_key(x_api_key)
    ejec = db.get(Ejecucion, ejecucion_id)
    if ejec is None:
        raise HTTPException(404, "Ejecución no encontrada")
    return ejec


@router.get("", response_model=list[EjecucionOut])
def ultimas_ejecuciones(limite: int = 20, db: Session = Depends(get_db),
                        x_api_key: str | None = Header(None)):
    verificar_api_key(x_api_key)
    return db.execute(
        select(Ejecucion).order_by(Ejecucion.inicio.desc()).limit(limite)
    ).scalars().all()
