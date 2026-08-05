"""Endpoints del panel (con JWT): resumen por estado, dashboard y log del robot."""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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


# ── meses ('AAAA-MM' en hora local de Bogotá) ───────────────────────────────────
_RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Tope del selector de meses: evita listar cientos de meses si hay una factura
# con fecha atípica en la BD.
_MAX_MESES_SELECTOR = 60


def _clave_mes(momento_utc: datetime) -> str:
    """Mes local (Bogotá) al que pertenece un instante guardado en UTC."""
    local = momento_utc - _DESFASE_BOGOTA
    return f"{local.year:04d}-{local.month:02d}"


def _validar_mes(clave: str) -> str:
    if not _RE_MES.match(clave):
        raise HTTPException(400, "El mes debe tener el formato AAAA-MM (ej: 2026-07)")
    return clave


def _sumar_meses(clave: str, n: int) -> str:
    anio, mes = int(clave[:4]), int(clave[5:7])
    total = anio * 12 + (mes - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _rango_mes_utc(clave: str) -> tuple[datetime, datetime]:
    """Límites [inicio, fin) en UTC del mes local 'AAAA-MM'."""
    anio, mes = int(clave[:4]), int(clave[5:7])
    siguiente = _sumar_meses(clave, 1)
    inicio = datetime(anio, mes, 1) + _DESFASE_BOGOTA
    fin = datetime(int(siguiente[:4]), int(siguiente[5:7]), 1) + _DESFASE_BOGOTA
    return inicio, fin


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
def dashboard(periodo: str = "mes", mes: str | None = None, meses: int = 12,
              db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    """Datos del dashboard de análisis.

    - `mes` ('AAAA-MM', por defecto el mes en curso): mes que alimenta las tarjetas
      y que ancla los cortes de `periodo` (así se puede analizar cualquier mes
      histórico, no solo el actual).
    - `por_area`: cantidad y valor por área en el `periodo` (mes|trimestre|anio|todo),
      siempre relativo al mes seleccionado.
    - `matriz`: gasto por área y por mes (ventana de `meses` meses que termina en el
      mes seleccionado) con totales por mes y acumulado corrido.
    - `mas_antiguas`: facturas pendientes con más días sin procesar (sin filtro de
      periodo: justamente las viejas son las que interesan).
    """
    ahora_utc = _ahora_utc()
    mes_sel = _validar_mes(mes) if mes else _clave_mes(ahora_utc)
    inicio_mes, fin_mes = _rango_mes_utc(mes_sel)
    meses = max(1, min(meses, 24))
    fecha_ref = func.coalesce(Factura.fecha_recepcion, Factura.creado_en)

    # ── tarjetas del mes seleccionado ──
    q_mes = (
        select(
            Factura.estado_proceso,
            func.count(),
            func.coalesce(func.sum(Factura.valor_total), 0),
        )
        .where(fecha_ref >= inicio_mes, fecha_ref < fin_mes)
        .group_by(Factura.estado_proceso)
    )
    q_mes = _alcance_por_rol(q_mes, usuario, db)
    filas_mes = db.execute(q_mes).all()
    mes_kpis = {
        "total": sum(n for _, n, _ in filas_mes),
        "pendientes": sum(n for e, n, _ in filas_mes if e in ESTADOS_PENDIENTES),
        "procesadas": sum(n for e, n, _ in filas_mes if e in ESTADOS_PROCESADAS),
        "valor_total": float(sum(v for _, _, v in filas_mes)),
    }

    # ── análisis por área (cantidad, valor, pendientes) en el periodo pedido ──
    # Los periodos relativos terminan en el mes seleccionado, no en hoy.
    if periodo == "trimestre":
        desde, hasta = _rango_mes_utc(_sumar_meses(mes_sel, -2))[0], fin_mes
    elif periodo == "anio":
        desde, hasta = _rango_mes_utc(f"{mes_sel[:4]}-01")[0], fin_mes
    elif periodo == "todo":
        desde, hasta = None, None
    else:  # "mes" (por defecto)
        desde, hasta = inicio_mes, fin_mes

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
        q_area = q_area.where(fecha_ref >= desde, fecha_ref < hasta)
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

    # ── matriz área × mes (acumulado mensual) ──
    # El bucketing por mes se hace en Python y no con DATEPART/strftime: las fechas
    # están en UTC y el mes del negocio es el de Bogotá (UTC-5), así que una factura
    # recibida a las 19:00-23:59 locales pertenece al día/mes siguiente en UTC.
    claves_meses = [_sumar_meses(mes_sel, -i) for i in range(meses - 1, -1, -1)]
    indice_mes = {clave: i for i, clave in enumerate(claves_meses)}
    inicio_ventana = _rango_mes_utc(claves_meses[0])[0]

    q_matriz = (
        select(Area.nombre, fecha_ref, Factura.valor_total)
        .select_from(Factura)
        .outerjoin(Area, Factura.area_id == Area.id)
        .where(fecha_ref >= inicio_ventana, fecha_ref < fin_mes)
    )
    q_matriz = _alcance_por_rol(q_matriz, usuario, db)
    valores_por_area: dict[str, list[float]] = {}
    for nombre, fecha, valor in db.execute(q_matriz).all():
        i = indice_mes.get(_clave_mes(fecha))
        if i is None:  # fuera de la ventana por el desfase horario
            continue
        fila = valores_por_area.setdefault(nombre or "Sin asignar", [0.0] * len(claves_meses))
        fila[i] += float(valor or 0)

    filas_matriz = sorted(
        (
            {"area": nombre, "valores": valores, "total": sum(valores)}
            for nombre, valores in valores_por_area.items()
        ),
        key=lambda f: f["total"],
        reverse=True,
    )
    totales_mes = [
        sum(fila["valores"][i] for fila in filas_matriz) for i in range(len(claves_meses))
    ]
    acumulado: list[float] = []
    corrido = 0.0
    for total in totales_mes:
        corrido += total
        acumulado.append(corrido)

    # Meses con datos, para el selector (del más reciente al más antiguo)
    primera_fecha = db.scalar(_alcance_por_rol(select(func.min(fecha_ref)), usuario, db))
    mes_actual = _clave_mes(ahora_utc)
    tope = max(mes_actual, mes_sel)
    clave = _clave_mes(primera_fecha) if primera_fecha else tope
    meses_disponibles = []
    while clave <= tope and len(meses_disponibles) < _MAX_MESES_SELECTOR:
        meses_disponibles.append(clave)
        clave = _sumar_meses(clave, 1)
    meses_disponibles.reverse()

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

    return {
        "mes": mes_kpis,
        "mes_seleccionado": mes_sel,
        "meses_disponibles": meses_disponibles,
        "por_area": por_area,
        "matriz": {
            "meses": claves_meses,
            "filas": filas_matriz,
            "totales_mes": totales_mes,
            "acumulado": acumulado,
            "total_general": acumulado[-1] if acumulado else 0.0,
        },
        "mas_antiguas": mas_antiguas,
        "periodo": periodo,
    }


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
