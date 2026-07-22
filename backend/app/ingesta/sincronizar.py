"""Sincronización idempotente: portal Siesa -> Blob + SQL.

Flujo de una corrida:
  1. Registrar una fila en `ejecuciones`.
  2. Login al portal y listar documentos del rango (por defecto, últimos N días).
  3. Por cada documento cuyo CUFE no exista aún en la BD:
       - upsert del proveedor,
       - descargar el PDF y subirlo al Blob,
       - crear la factura (estado 'nueva') y su documento FV,
       - asignar área/responsable con las reglas,
       - reevaluar completitud y registrar el evento.
  4. Cerrar la ejecución con contadores.

Es idempotente: una segunda corrida sobre el mismo rango no duplica nada
(se filtra por CUFE ya existente).
"""
from __future__ import annotations

import logging
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Documento, Ejecucion, Evento, Factura, Proveedor, ahora
from ..services import reglas
from ..services.blob_storage import get_almacen
from .siesa_client import DocumentoPortal, SiesaClient

log = logging.getLogger("ingesta")


def _upsert_proveedor(db: Session, nit: str, razon_social: str) -> Proveedor:
    prov = db.execute(select(Proveedor).where(Proveedor.nit == nit)).scalar_one_or_none()
    if prov is None:
        prov = Proveedor(nit=nit, razon_social=razon_social or nit)
        db.add(prov)
        db.flush()
    elif razon_social and prov.razon_social != razon_social:
        prov.razon_social = razon_social
    return prov


def _ruta_blob(nit: str, folio: str, fecha: datetime | None, ext: str = "pdf") -> str:
    f = fecha or datetime.utcnow()
    folio_limpio = "".join(c for c in folio if c.isalnum() or c in "-_") or "sin_folio"
    return f"facturas/{f.year:04d}/{f.month:02d}/{nit}_{folio_limpio}.{ext}"


def _existe_cufe(db: Session, cufe: str) -> bool:
    if not cufe:
        return False
    return db.execute(
        select(Factura.id).where(Factura.cufe == cufe)
    ).first() is not None


def _crear_factura(db: Session, doc: DocumentoPortal, siesa: SiesaClient, almacen) -> Factura:
    prov = _upsert_proveedor(db, doc.nit_emisor, doc.emisor)

    # Descargar y subir el PDF (documento FV)
    pdf = siesa.descargar_pdf(doc.cufe, doc.fecha)
    ruta = _ruta_blob(doc.nit_emisor, doc.folio, doc.fecha)
    almacen.subir(ruta, pdf, content_type="application/pdf")

    factura = Factura(
        cufe=doc.cufe,
        prefijo="",
        numero=doc.folio,
        proveedor_id=prov.id,
        fecha_emision=doc.fecha,
        fecha_recepcion=ahora(),
        valor_total=doc.valor,
        estado_portal=doc.estado_adquiriente,
        estado_proceso="nueva",
        blob_pdf=ruta,
    )
    db.add(factura)
    db.flush()

    db.add(Documento(
        factura_id=factura.id,
        tipo="FV",
        blob_path=ruta,
        nombre_archivo=f"{doc.nit_emisor}_{doc.folio}.pdf",
        subido_por_id=None,
    ))
    db.add(Evento(factura_id=factura.id, accion="ingesta",
                  detalle=f"Descargada del portal (folio {doc.folio})"))

    reglas.asignar_area(db, factura)
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.flush()
    return factura


def sincronizar(db: Session, dias: int = 3,
                fecha_desde: str | None = None, fecha_hasta: str | None = None,
                limite: int | None = None) -> dict:
    """Ejecuta una corrida de ingesta. Devuelve un resumen para n8n/logs.

    limite: si se indica, procesa como máximo esa cantidad de facturas nuevas
    (útil para pruebas y para acotar corridas muy grandes).
    """
    hoy = date.today()
    desde = fecha_desde or (hoy - timedelta(days=dias)).isoformat()
    hasta = fecha_hasta or hoy.isoformat()

    ejec = Ejecucion(inicio=ahora(), estado="en_curso")
    db.add(ejec)
    db.commit()

    almacen = get_almacen()
    nuevas = 0
    errores = 0
    detalles: list[str] = []
    sin_area: list[str] = []

    try:
        with SiesaClient(settings.url_facturas, settings.username_facturas,
                         settings.password_facturas) as siesa:
            docs = siesa.listar_documentos(desde, hasta)
            log.info("Portal devolvió %d documentos (%s..%s)", len(docs), desde, hasta)

            for doc in docs:
                if limite is not None and nuevas >= limite:
                    log.info("Alcanzado el límite de %d facturas nuevas", limite)
                    break
                if _existe_cufe(db, doc.cufe):
                    continue
                try:
                    f = _crear_factura(db, doc, siesa, almacen)
                    db.commit()
                    nuevas += 1
                    if f.area_id is None:
                        sin_area.append(doc.folio)
                except Exception as e:  # noqa: BLE001 — no abortar toda la corrida por una factura
                    db.rollback()
                    errores += 1
                    detalles.append(f"{doc.folio}: {e}")
                    log.exception("Error procesando %s", doc.folio)

        ejec.estado = "ok" if errores == 0 else "error"
    except Exception as e:  # noqa: BLE001
        ejec.estado = "error"
        detalles.append(f"Fallo general: {e}")
        log.error("Fallo general de la ingesta:\n%s", traceback.format_exc())
    finally:
        ejec.fin = ahora()
        ejec.facturas_nuevas = nuevas
        ejec.errores = errores
        ejec.detalle = "\n".join(detalles)[:4000] if detalles else None
        db.commit()

    return {
        "ejecucion_id": ejec.id,
        "estado": ejec.estado,
        "rango": {"desde": desde, "hasta": hasta},
        "facturas_nuevas": nuevas,
        "errores": errores,
        "sin_area_asignada": sin_area,
        "detalle": detalles,
    }
