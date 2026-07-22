"""Reglas de negocio: asignación de área/responsable y completitud de documentos."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Documento, Factura, ReglaArea


def asignar_area(db: Session, factura: Factura) -> None:
    """Asigna área y responsable a una factura según las reglas del proveedor.

    Un proveedor puede tener varias áreas candidatas (p. ej. factura tanto a
    Mantenimiento como a Producción). Si solo tiene una, se asigna directo. Si
    tiene varias, se intenta desambiguar por patrón de ítem (descripciones de
    la factura); si ninguna coincide, la factura queda sin área — no se adivina —
    hasta que la extracción de ítems (IA) o un admin la resuelvan.
    """
    nit = factura.proveedor.nit if factura.proveedor else None
    if not nit:
        return
    reglas = db.execute(
        select(ReglaArea).where(ReglaArea.proveedor_nit == nit)
    ).scalars().all()
    if not reglas:
        return

    areas_candidatas = {r.area_id for r in reglas}
    if len(areas_candidatas) == 1:
        elegida = reglas[0]
    else:
        texto = _texto_para_patrones(factura)
        elegida = next(
            (r for r in reglas if r.patron_item and r.patron_item.lower() in texto),
            None,
        )

    if elegida:
        factura.area_id = elegida.area_id
        factura.responsable_id = elegida.responsable_id
        if factura.estado_proceso == "nueva":
            factura.estado_proceso = "asignada"


def _texto_para_patrones(factura: Factura) -> str:
    """Texto sobre el que se evalúan los patrones de ítem para desambiguar área.

    Incluye proveedor + folio como base; si la factura tiene ítems extraídos
    (IA), se agregan sus descripciones para permitir un match más preciso.
    """
    partes = [factura.proveedor.razon_social, factura.numero]
    items = getattr(factura, "items", None)
    if items:
        partes += [i.descripcion for i in items if i.descripcion]
    return " ".join(partes).lower()


def _tipos_cargados(db: Session, factura: Factura) -> set[str]:
    return {
        d.tipo for d in db.execute(
            select(Documento).where(Documento.factura_id == factura.id)
        ).scalars().all()
    }


def faltan_documentos(db: Session, factura: Factura) -> list[str]:
    """Lista legible de documentos que faltan para poder contabilizar.

    Regla del proceso:
      - FV: siempre (el PDF descargado del portal cuenta como FV).
      - Orden: se requiere OCN (orden de compra) u OCS (orden de servicio).
      - CRN: solo si la orden es OCN (recepción de mercancía).
    Mientras no se cargue la orden, no se sabe si hará falta CRN.
    """
    tipos = _tipos_cargados(db, factura)
    faltan: list[str] = []
    if "FV" not in tipos:
        faltan.append("FV")

    tiene_ocn = "OCN" in tipos
    tiene_ocs = "OCS" in tipos
    if not (tiene_ocn or tiene_ocs):
        faltan.append("OCN u OCS")
    elif tiene_ocn and "CRN" not in tipos:
        faltan.append("CRN")
    return faltan


def inferir_tipo_orden(db: Session, factura: Factura) -> None:
    """Deduce tipo_orden a partir de las órdenes cargadas (OCN prevalece)."""
    tipos = _tipos_cargados(db, factura)
    if "OCN" in tipos:
        factura.tipo_orden = "OCN"
    elif "OCS" in tipos:
        factura.tipo_orden = "OCS"


def evaluar_completitud(db: Session, factura: Factura) -> None:
    """Recalcula el estado_proceso de la factura según los documentos cargados.

    No degrada un estado 'contabilizada' (eso lo controla contabilidad).
    """
    if factura.estado_proceso == "contabilizada":
        return

    inferir_tipo_orden(db, factura)
    faltantes = faltan_documentos(db, factura)

    if not faltantes:
        factura.estado_proceso = "lista_contabilizar"
    elif factura.area_id is not None:
        factura.estado_proceso = "docs_pendientes"
    else:
        factura.estado_proceso = "nueva"
