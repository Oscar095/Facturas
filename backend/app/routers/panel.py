"""Endpoints del panel (con JWT): resumen por estado, dashboard y log del robot."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal, get_db
from ..ingesta.sincronizar import sincronizar
from ..models import Area, Ejecucion, Factura, Usuario
from ..schemas import EjecucionOut
from ..security import requiere_permiso, tiene_permiso, usuario_actual

router = APIRouter(prefix="/api/panel", tags=["panel"])

# Pendientes = aún les faltan documentos o gestión; procesadas = documentos
# listos (automático o declarado) y de ahí en adelante (aprobada, contabilizada)
ESTADOS_PENDIENTES = ("nueva", "asignada", "docs_pendientes")
ESTADOS_PROCESADAS = ("lista_contabilizar", "procesada", "aprobada", "contabilizada")

# Las fechas se guardan en UTC naive; el negocio opera en Colombia (UTC-5, sin
# horario de verano), así que los cortes de mes/año se calculan en hora local.
_DESFASE_BOGOTA = timedelta(hours=5)


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _inicio_mes_utc(ahora_utc: datetime) -> datetime:
    local = ahora_utc - _DESFASE_BOGOTA
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + _DESFASE_BOGOTA


def _inicio_anio_utc(ahora_utc: datetime) -> datetime:
    local = ahora_utc - _DESFASE_BOGOTA
    return local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) + _DESFASE_BOGOTA


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
    q = _alcance_por_rol(q, usuario, db)
    conteos = {estado: n for estado, n in db.execute(q).all()}
    orden = ["nueva", "asignada", "docs_pendientes", "lista_contabilizar",
             "procesada", "aprobada", "contabilizada"]
    return {
        "por_estado": {e: conteos.get(e, 0) for e in orden},
        "total": sum(conteos.values()),
    }


def _alcance_por_rol(q, usuario: Usuario, db: Session):
    """Sin el permiso 'ver_todas_areas', el usuario solo ve cifras de su área."""
    if not tiene_permiso(db, usuario, "ver_todas_areas"):
        if usuario.area_id is None:
            return q.where(Factura.id == -1)
        return q.where(Factura.area_id == usuario.area_id)
    return q


@router.get("/dashboard")
def dashboard(periodo: str = "mes", db: Session = Depends(get_db),
              usuario: Usuario = Depends(usuario_actual)):
    """Datos del dashboard de análisis.

    - `mes`: tarjetas del mes actual (total, pendientes, procesadas, valor).
    - `por_area`: cantidad y valor por área en el `periodo` (mes|trimestre|anio|todo).
    - `mas_antiguas`: facturas pendientes con más días sin procesar (sin filtro de
      periodo: justamente las viejas son las que interesan).
    """
    ahora_utc = _ahora_utc()
    inicio_mes = _inicio_mes_utc(ahora_utc)
    fecha_ref = func.coalesce(Factura.fecha_recepcion, Factura.creado_en)

    # ── tarjetas del mes actual ──
    q_mes = (
        select(
            Factura.estado_proceso,
            func.count(),
            func.coalesce(func.sum(Factura.valor_total), 0),
        )
        .where(fecha_ref >= inicio_mes)
        .group_by(Factura.estado_proceso)
    )
    q_mes = _alcance_por_rol(q_mes, usuario, db)
    filas_mes = db.execute(q_mes).all()
    mes = {
        "total": sum(n for _, n, _ in filas_mes),
        "pendientes": sum(n for e, n, _ in filas_mes if e in ESTADOS_PENDIENTES),
        "procesadas": sum(n for e, n, _ in filas_mes if e in ESTADOS_PROCESADAS),
        "valor_total": float(sum(v for _, _, v in filas_mes)),
    }

    # ── análisis por área (cantidad, valor, pendientes) en el periodo pedido ──
    if periodo == "trimestre":
        desde = ahora_utc - timedelta(days=90)
    elif periodo == "anio":
        desde = _inicio_anio_utc(ahora_utc)
    elif periodo == "todo":
        desde = None
    else:  # "mes" (por defecto)
        desde = inicio_mes

    q_area = (
        select(
            Area.nombre,
            func.count(Factura.id),
            func.coalesce(func.sum(Factura.valor_total), 0),
            func.sum(case((Factura.estado_proceso.in_(ESTADOS_PENDIENTES), 1), else_=0)),
        )
        .select_from(Factura)
        .outerjoin(Area, Factura.area_id == Area.id)
        .group_by(Area.nombre)
    )
    if desde is not None:
        q_area = q_area.where(fecha_ref >= desde)
    q_area = _alcance_por_rol(q_area, usuario, db)
    por_area = sorted(
        (
            {
                "area": nombre or "Sin asignar",
                "cantidad": cantidad,
                "valor": float(valor),
                "pendientes": int(pendientes or 0),
            }
            for nombre, cantidad, valor, pendientes in db.execute(q_area).all()
        ),
        key=lambda a: a["valor"],
        reverse=True,
    )

    # ── facturas pendientes con más tiempo sin procesar ──
    q_viejas = (
        select(Factura)
        .options(joinedload(Factura.proveedor), joinedload(Factura.area))
        .where(Factura.estado_proceso.in_(ESTADOS_PENDIENTES))
        .order_by(fecha_ref.asc())
        .limit(10)
    )
    q_viejas = _alcance_por_rol(q_viejas, usuario, db)
    mas_antiguas = []
    for f in db.execute(q_viejas).scalars().all():
        recibida = f.fecha_recepcion or f.creado_en
        mas_antiguas.append({
            "id": f.id,
            "numero": f.numero,
            "proveedor": f.proveedor.razon_social if f.proveedor else "—",
            "area": f.area.nombre if f.area else None,
            "valor_total": float(f.valor_total) if f.valor_total is not None else None,
            "fecha_recepcion": recibida.isoformat() if recibida else None,
            "dias_sin_procesar": (ahora_utc - recibida).days if recibida else None,
            "estado_proceso": f.estado_proceso,
        })

    return {"mes": mes, "por_area": por_area, "mas_antiguas": mas_antiguas, "periodo": periodo}


@router.get("/ejecuciones", response_model=list[EjecucionOut])
def ejecuciones(limite: int = 20, db: Session = Depends(get_db),
                _: Usuario = Depends(requiere_permiso("administrar", "contabilizar"))):
    return db.execute(
        select(Ejecucion).order_by(Ejecucion.inicio.desc()).limit(limite)
    ).scalars().all()


@router.post("/sincronizar")
def sincronizar_ahora(background: BackgroundTasks, dias: int = 3,
                      _: Usuario = Depends(requiere_permiso("administrar"))):
    """Dispara la ingesta manualmente desde el portal (solo admin).

    Corre en segundo plano (puede tardar varios minutos); el resultado se
    consulta en /api/panel/ejecuciones una vez termine.
    """
    background.add_task(_correr_sync_en_fondo, dias)
    return {"ok": True, "mensaje": "Sincronización iniciada. Revisa el log en unos minutos."}
