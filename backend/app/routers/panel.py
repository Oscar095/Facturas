"""Endpoints del panel (con JWT): resumen por estado, dashboard y log del robot."""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from ..database import SessionLocal, get_db
from ..ingesta.sincronizar import sincronizar
from ..models import Area, Ejecucion, Factura, NotaCredito, Usuario
from ..schemas import EjecucionOut
from ..security import requiere_permiso, tiene_permiso, usuario_actual

router = APIRouter(prefix="/api/panel", tags=["panel"])

# Pendientes = aún les faltan documentos o gestión; procesadas = documentos
# listos (automático o declarado) y de ahí en adelante (aprobada, contabilizada)
ESTADOS_PENDIENTES = ("nueva", "asignada", "docs_pendientes")
ESTADOS_PROCESADAS = ("lista_contabilizar", "procesada", "aprobada", "contabilizada")

# fecha_recepcion/creado_en se guardan en UTC pero el negocio opera en Bogotá
# (UTC-5, sin horario de verano): el desfase se usa para saber en qué mes LOCAL
# estamos y cuántos días lleva un documento sin procesar.
_DESFASE_BOGOTA = timedelta(hours=5)

# ── qué fecha mide el panel ───────────────────────────────────────────────────
# TODO el dashboard mide por la FECHA DE EMISIÓN del documento (la que le puso el
# proveedor), NO por la fecha en que el robot lo descargó: una factura emitida el
# 30 de julio y recibida el 2 de agosto es gasto de JULIO. No devolver esto a
# fecha_recepcion.
# La emisión se guarda tal cual la entrega el portal — hora local de Colombia, a
# las 00:00 — así que los cortes de mes van en hora LOCAL, sin el desfase que sí
# necesitaría fecha_recepcion. El coalesce es solo una red: hoy ninguna fila tiene
# la emisión vacía, pero la carga manual permite crear una factura sin ella (esas
# pocas pueden desviarse hasta 5 horas en el corte de mes, y da igual).
_EMISION = func.coalesce(Factura.fecha_emision, Factura.fecha_recepcion, Factura.creado_en)
_EMISION_NC = func.coalesce(
    NotaCredito.fecha_emision, NotaCredito.fecha_recepcion, NotaCredito.creado_en
)

# Todo el panel mide SIN IVA: el seguimiento del negocio se hace sobre la base.
# Donde el IVA no se pudo determinar (documentos escaneados, sin texto_pdf) el
# coalesce deja el total tal cual — se prefiere sumar de más antes que excluir el
# documento del análisis. Ver services/iva.py.
_VALOR_SIN_IVA = Factura.valor_total - func.coalesce(Factura.iva, 0)
_VALOR_SIN_IVA_NC = NotaCredito.valor_total - func.coalesce(NotaCredito.iva, 0)


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ahora_local() -> datetime:
    """Ahora en hora de Bogotá — la misma escala en la que están las emisiones."""
    return _ahora_utc() - _DESFASE_BOGOTA


# ── meses ('AAAA-MM' en hora local de Bogotá) ───────────────────────────────────
_RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
# Tope del selector de meses: evita listar cientos de meses si hay una factura
# con fecha atípica en la BD.
_MAX_MESES_SELECTOR = 60


def _clave_mes(momento: datetime) -> str:
    """Mes 'AAAA-MM' de una fecha ya en hora local (emisión, o _ahora_local())."""
    return f"{momento.year:04d}-{momento.month:02d}"


def _validar_mes(clave: str) -> str:
    if not _RE_MES.match(clave):
        raise HTTPException(400, "El mes debe tener el formato AAAA-MM (ej: 2026-07)")
    return clave


def _sumar_meses(clave: str, n: int) -> str:
    anio, mes = int(clave[:4]), int(clave[5:7])
    total = anio * 12 + (mes - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _rango_mes(clave: str) -> tuple[datetime, datetime]:
    """Límites [inicio, fin) del mes local 'AAAA-MM'."""
    anio, mes = int(clave[:4]), int(clave[5:7])
    siguiente = _sumar_meses(clave, 1)
    return (datetime(anio, mes, 1),
            datetime(int(siguiente[:4]), int(siguiente[5:7]), 1))


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


def _alcance_por_rol(q, usuario: Usuario, db: Session, modelo=Factura):
    """Sin el permiso 'ver_todas_areas', el usuario solo ve cifras de su área.

    `modelo` permite aplicar el mismo alcance a las notas crédito, que también
    tienen area_id (ver routers/notas_credito.py).
    """
    if not tiene_permiso(db, usuario, "ver_todas_areas"):
        if usuario.area_id is None:
            return q.where(modelo.id == -1)
        return q.where(modelo.area_id == usuario.area_id)
    return q


def _fila_area(nombre: str | None) -> dict:
    return {"area": nombre or "Sin asignar", "cantidad": 0, "facturado": 0.0,
            "notas_credito": 0, "valor_notas_credito": 0.0, "pendientes": 0}


@router.get("/dashboard")
def dashboard(periodo: str = "mes", mes: str | None = None, meses: int = 12,
              db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_actual)):
    """Datos del dashboard de análisis.

    Todo se mide por **fecha de emisión** y **sin IVA**, y las notas crédito
    **restan** del área a la que corresponden: las cifras son el gasto neto.

    - `mes` ('AAAA-MM', por defecto el mes en curso): mes que alimenta las tarjetas
      y que ancla los cortes de `periodo` (así se puede analizar cualquier mes
      histórico, no solo el actual).
    - `por_area`: cantidad y valor neto por área en el `periodo` (mes|trimestre|
      anio|todo), siempre relativo al mes seleccionado.
    - `matriz`: gasto neto por área y por mes (ventana de `meses` meses que termina
      en el mes seleccionado) con totales por mes y acumulado corrido.
    - `mas_antiguas`: facturas pendientes con más tiempo desde su emisión (sin
      filtro de periodo: justamente las viejas son las que interesan).
    """
    ahora_local = _ahora_local()
    mes_sel = _validar_mes(mes) if mes else _clave_mes(ahora_local)
    inicio_mes, fin_mes = _rango_mes(mes_sel)
    meses = max(1, min(meses, 24))

    # ── tarjetas del mes seleccionado ──
    q_mes = (
        select(
            Factura.estado_proceso,
            func.count(),
            func.coalesce(func.sum(_VALOR_SIN_IVA), 0),
        )
        .where(_EMISION >= inicio_mes, _EMISION < fin_mes)
        .group_by(Factura.estado_proceso)
    )
    q_mes = _alcance_por_rol(q_mes, usuario, db)
    filas_mes = db.execute(q_mes).all()

    q_nc_mes = (
        select(func.count(), func.coalesce(func.sum(_VALOR_SIN_IVA_NC), 0))
        .select_from(NotaCredito)
        .where(_EMISION_NC >= inicio_mes, _EMISION_NC < fin_mes)
    )
    q_nc_mes = _alcance_por_rol(q_nc_mes, usuario, db, NotaCredito)
    nc_cantidad, nc_valor = db.execute(q_nc_mes).one()

    facturado_mes = float(sum(v for _, _, v in filas_mes))
    creditos_mes = float(nc_valor or 0)
    mes_kpis = {
        "total": sum(n for _, n, _ in filas_mes),
        "pendientes": sum(n for e, n, _ in filas_mes if e in ESTADOS_PENDIENTES),
        "procesadas": sum(n for e, n, _ in filas_mes if e in ESTADOS_PROCESADAS),
        "facturado": facturado_mes,
        "notas_credito": int(nc_cantidad or 0),
        "valor_notas_credito": creditos_mes,
        # neto = lo facturado menos las notas crédito emitidas en el mismo mes
        "valor_total": facturado_mes - creditos_mes,
    }

    # ── análisis por área (cantidad, valor neto, pendientes) en el periodo pedido ──
    # Los periodos relativos terminan en el mes seleccionado, no en hoy.
    if periodo == "trimestre":
        desde, hasta = _rango_mes(_sumar_meses(mes_sel, -2))[0], fin_mes
    elif periodo == "anio":
        desde, hasta = _rango_mes(f"{mes_sel[:4]}-01")[0], fin_mes
    elif periodo == "todo":
        desde, hasta = None, None
    else:  # "mes" (por defecto)
        desde, hasta = inicio_mes, fin_mes

    q_area = (
        select(
            Area.nombre,
            func.count(Factura.id),
            func.coalesce(func.sum(_VALOR_SIN_IVA), 0),
            func.sum(case((Factura.estado_proceso.in_(ESTADOS_PENDIENTES), 1), else_=0)),
        )
        .select_from(Factura)
        .outerjoin(Area, Factura.area_id == Area.id)
        .group_by(Area.nombre)
    )
    q_nc_area = (
        select(
            Area.nombre,
            func.count(NotaCredito.id),
            func.coalesce(func.sum(_VALOR_SIN_IVA_NC), 0),
        )
        .select_from(NotaCredito)
        .outerjoin(Area, NotaCredito.area_id == Area.id)
        .group_by(Area.nombre)
    )
    if desde is not None:
        q_area = q_area.where(_EMISION >= desde, _EMISION < hasta)
        q_nc_area = q_nc_area.where(_EMISION_NC >= desde, _EMISION_NC < hasta)
    q_area = _alcance_por_rol(q_area, usuario, db)
    q_nc_area = _alcance_por_rol(q_nc_area, usuario, db, NotaCredito)

    areas: dict[str, dict] = {}
    for nombre, cantidad, valor, pendientes in db.execute(q_area).all():
        fila = areas.setdefault(nombre or "Sin asignar", _fila_area(nombre))
        fila["cantidad"] = cantidad
        fila["facturado"] = float(valor)
        fila["pendientes"] = int(pendientes or 0)
    # Un área puede aparecer SOLO por sus notas crédito (crédito de un mes anterior):
    # se lista igual, con cantidad 0 y valor negativo. Es la cifra real del periodo.
    for nombre, cantidad, valor in db.execute(q_nc_area).all():
        fila = areas.setdefault(nombre or "Sin asignar", _fila_area(nombre))
        fila["notas_credito"] = cantidad
        fila["valor_notas_credito"] = float(valor)

    por_area = sorted(
        ({**f, "valor": f["facturado"] - f["valor_notas_credito"]} for f in areas.values()),
        key=lambda a: a["valor"],
        reverse=True,
    )

    # ── matriz área × mes (acumulado mensual neto) ──
    # El bucketing por mes se hace en Python y no con DATEPART/strftime: así no se
    # depende del dialecto (Azure SQL vs SQLite local) y el corte queda donde lo
    # pone la emisión, sin traducciones de huso.
    claves_meses = [_sumar_meses(mes_sel, -i) for i in range(meses - 1, -1, -1)]
    indice_mes = {clave: i for i, clave in enumerate(claves_meses)}
    inicio_ventana = _rango_mes(claves_meses[0])[0]

    q_matriz = (
        select(Area.nombre, _EMISION, _VALOR_SIN_IVA)
        .select_from(Factura)
        .outerjoin(Area, Factura.area_id == Area.id)
        .where(_EMISION >= inicio_ventana, _EMISION < fin_mes)
    )
    q_matriz = _alcance_por_rol(q_matriz, usuario, db)
    q_matriz_nc = (
        select(Area.nombre, _EMISION_NC, _VALOR_SIN_IVA_NC)
        .select_from(NotaCredito)
        .outerjoin(Area, NotaCredito.area_id == Area.id)
        .where(_EMISION_NC >= inicio_ventana, _EMISION_NC < fin_mes)
    )
    q_matriz_nc = _alcance_por_rol(q_matriz_nc, usuario, db, NotaCredito)

    valores_por_area: dict[str, list[float]] = {}

    def _acumular(nombre: str | None, fecha: datetime | None, valor, signo: int):
        i = indice_mes.get(_clave_mes(fecha)) if fecha else None
        if i is None:  # fuera de la ventana
            return
        fila = valores_por_area.setdefault(
            nombre or "Sin asignar", [0.0] * len(claves_meses)
        )
        fila[i] += signo * float(valor or 0)

    for nombre, fecha, valor in db.execute(q_matriz).all():
        _acumular(nombre, fecha, valor, 1)
    for nombre, fecha, valor in db.execute(q_matriz_nc).all():
        _acumular(nombre, fecha, valor, -1)  # la nota crédito resta

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
    primeras = [
        db.scalar(_alcance_por_rol(select(func.min(_EMISION)), usuario, db)),
        db.scalar(_alcance_por_rol(
            select(func.min(_EMISION_NC)).select_from(NotaCredito), usuario, db, NotaCredito
        )),
    ]
    con_datos = [f for f in primeras if f]
    mes_actual = _clave_mes(ahora_local)
    tope = max(mes_actual, mes_sel)
    clave = _clave_mes(min(con_datos)) if con_datos else tope
    meses_disponibles = []
    while clave <= tope and len(meses_disponibles) < _MAX_MESES_SELECTOR:
        meses_disponibles.append(clave)
        clave = _sumar_meses(clave, 1)
    meses_disponibles.reverse()

    # ── facturas pendientes con más tiempo desde su emisión ──
    q_viejas = (
        select(Factura)
        .options(joinedload(Factura.proveedor), joinedload(Factura.area))
        .where(Factura.estado_proceso.in_(ESTADOS_PENDIENTES))
        .order_by(_EMISION.asc())
        .limit(10)
    )
    q_viejas = _alcance_por_rol(q_viejas, usuario, db)
    mas_antiguas = []
    for f in db.execute(q_viejas).scalars().all():
        emitida = f.fecha_emision or f.fecha_recepcion or f.creado_en
        mas_antiguas.append({
            "id": f.id,
            "numero": f.numero,
            "proveedor": f.proveedor.razon_social if f.proveedor else "—",
            "area": f.area.nombre if f.area else None,
            # sin IVA, igual que el resto del panel
            "valor_total": float(f.valor_total - (f.iva or 0)) if f.valor_total is not None else None,
            "fecha_emision": emitida.isoformat() if emitida else None,
            # días desde que el proveedor la emitió, no desde que el robot la bajó
            "dias_sin_procesar": (ahora_local - emitida).days if emitida else None,
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
