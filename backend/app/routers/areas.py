import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Area, ReglaArea, Usuario
from ..schemas import AreaBase, AreaOut, ReglaAreaBase, ReglaAreaOut
from ..security import requiere_rol, usuario_actual

router = APIRouter(prefix="/api/areas", tags=["areas"])


@router.get("", response_model=list[AreaOut])
def listar_areas(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    return db.execute(select(Area).order_by(Area.nombre)).scalars().all()


@router.post("", response_model=AreaOut)
def crear_area(datos: AreaBase, db: Session = Depends(get_db),
               _: Usuario = Depends(requiere_rol("admin"))):
    if db.execute(select(Area).where(Area.nombre == datos.nombre)).scalar_one_or_none():
        raise HTTPException(400, "Ya existe un área con ese nombre")
    area = Area(**datos.model_dump())
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


# ── reglas proveedor/ítem -> área ────────────────────────────────────────────────
@router.get("/reglas", response_model=list[ReglaAreaOut])
def listar_reglas(db: Session = Depends(get_db), _: Usuario = Depends(requiere_rol("admin"))):
    return db.execute(select(ReglaArea)).scalars().all()


@router.post("/reglas", response_model=ReglaAreaOut)
def crear_regla(datos: ReglaAreaBase, db: Session = Depends(get_db),
                _: Usuario = Depends(requiere_rol("admin"))):
    regla = ReglaArea(**datos.model_dump())
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.delete("/reglas/{regla_id}")
def eliminar_regla(regla_id: int, db: Session = Depends(get_db),
                   _: Usuario = Depends(requiere_rol("admin"))):
    regla = db.get(ReglaArea, regla_id)
    if regla is None:
        raise HTTPException(404, "Regla no encontrada")
    db.delete(regla)
    db.commit()
    return {"ok": True}


@router.post("/reglas/importar")
def importar_reglas(archivo: UploadFile = File(...), db: Session = Depends(get_db),
                    _: Usuario = Depends(requiere_rol("admin"))):
    """Importa el Excel proveedor/ítem -> área.

    Columnas esperadas (por nombre en la primera fila, sin distinción de mayúsculas):
      nit | proveedor_nit  (requerida)
      area                 (requerida, nombre del área; se crea si no existe)
      patron_item | item   (opcional)
      responsable_email    (opcional)
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(archivo.file.read()), read_only=True, data_only=True)
    ws = wb.active
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        raise HTTPException(400, "El archivo está vacío")

    encabezados = [str(c).strip().lower() if c is not None else "" for c in filas[0]]

    def col(*nombres):
        for n in nombres:
            if n in encabezados:
                return encabezados.index(n)
        return None

    i_nit = col("nit", "proveedor_nit")
    i_area = col("area", "área")
    i_patron = col("patron_item", "patron", "item", "ítem")
    i_resp = col("responsable_email", "responsable", "email")
    if i_nit is None or i_area is None:
        raise HTTPException(400, "El Excel debe tener columnas 'nit' y 'area'")

    areas_cache = {a.nombre.lower(): a for a in db.execute(select(Area)).scalars().all()}
    usuarios_cache = {u.email.lower(): u for u in db.execute(select(Usuario)).scalars().all()}

    creadas = 0
    for fila in filas[1:]:
        if not fila or fila[i_nit] is None:
            continue
        nit = str(fila[i_nit]).strip()
        nombre_area = str(fila[i_area]).strip()
        if not nit or not nombre_area:
            continue
        area = areas_cache.get(nombre_area.lower())
        if area is None:
            area = Area(nombre=nombre_area)
            db.add(area)
            db.flush()
            areas_cache[nombre_area.lower()] = area
        patron = str(fila[i_patron]).strip() if i_patron is not None and fila[i_patron] else None
        resp = None
        if i_resp is not None and fila[i_resp]:
            resp = usuarios_cache.get(str(fila[i_resp]).strip().lower())

        existente = db.execute(
            select(ReglaArea).where(
                ReglaArea.proveedor_nit == nit, ReglaArea.patron_item == patron
            )
        ).scalar_one_or_none()
        if existente:
            existente.area_id = area.id
            if resp:
                existente.responsable_id = resp.id
        else:
            db.add(ReglaArea(proveedor_nit=nit, patron_item=patron, area_id=area.id,
                             responsable_id=resp.id if resp else None))
            creadas += 1

    db.commit()
    return {"reglas_creadas": creadas}
