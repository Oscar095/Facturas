"""Sincronización idempotente: portal Siesa -> Blob + SQL.

Flujo de una corrida (todo dentro de la misma sesión de navegador):
  1. Registrar una fila en `ejecuciones`.
  2. Login al portal y listar 3 tipos de documento del rango:
       - Facturas (tipo_doc=1) y Documentos Equivalentes (tipo_doc=20): ambos
         crean una Factura (diferenciados por `tipo_documento`) con su documento
         FV, asignación de área por reglas y evaluación de completitud.
       - Notas Crédito (tipo_doc=91): módulo aparte (tabla `notas_credito`),
         con asignación de área por reglas (sin IA) pero sin documentos ni
         flujo de completitud/aprobación.
  3. Cerrar la ejecución con contadores (facturas_nuevas, notas_credito_nuevas).

Es idempotente: una segunda corrida sobre el mismo rango no duplica nada
(dedup por CUFE contra la tabla que corresponde). Un fallo por-documento hace
rollback de ese documento y continúa con los demás.
"""
from __future__ import annotations

import logging
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Documento, Ejecucion, Evento, Factura, NotaCredito, Proveedor, ahora
from ..services import reglas
from ..services.blob_storage import get_almacen
from ..services.pdf_texto import extraer_texto
from ..services.iva import resolver_iva
from ..services.vencimiento import resolver_vencimiento
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


def _ruta_blob(nit: str, folio: str, fecha: datetime | None, ext: str = "pdf",
              carpeta: str = "facturas") -> str:
    f = fecha or datetime.utcnow()
    folio_limpio = "".join(c for c in folio if c.isalnum() or c in "-_") or "sin_folio"
    return f"{carpeta}/{f.year:04d}/{f.month:02d}/{nit}_{folio_limpio}.{ext}"


def _existe_cufe(db: Session, cufe: str) -> bool:
    if not cufe:
        return False
    return db.execute(
        select(Factura.id).where(Factura.cufe == cufe)
    ).first() is not None


def _existe_cufe_nc(db: Session, cufe: str) -> bool:
    if not cufe:
        return False
    return db.execute(
        select(NotaCredito.id).where(NotaCredito.cufe == cufe)
    ).first() is not None


def _crear_factura(db: Session, doc: DocumentoPortal, siesa: SiesaClient, almacen,
                   tipo_documento: str = "FACTURA", usar_ia_vencimiento: bool = False,
                   usar_ia_iva: bool = False) -> Factura:
    prov = _upsert_proveedor(db, doc.nit_emisor, doc.emisor)

    # Descargar y subir el PDF (documento FV; un Documento Equivalente lo reemplaza
    # funcionalmente, así que sigue contando como FV para completitud/aprobación).
    # La grilla de descarga debe fijarse al MISMO tipo del documento o el CUFE no aparece.
    tipo_doc_portal = "20" if tipo_documento == "EQUIVALENTE" else "1"
    pdf = siesa.descargar_pdf(doc.cufe, doc.fecha, tipo_doc=tipo_doc_portal)
    ruta = _ruta_blob(doc.nit_emisor, doc.folio, doc.fecha)
    almacen.subir(ruta, pdf, content_type="application/pdf")

    # texto de la factura: patrones de ítem (reglas de área), fecha de vencimiento e IVA
    texto = extraer_texto(pdf)
    vencimiento, venc_por_ia = resolver_vencimiento(
        texto, doc.fecha, pdf=pdf, usar_ia=usar_ia_vencimiento
    )
    # El portal solo entrega el total: el IVA se deduce del texto reconciliándolo
    # contra ese total (services/iva.py) y, si eso falla, con IA como último
    # recurso. None = no se pudo determinar (la UI lo marca).
    iva, iva_por_ia = resolver_iva(texto, doc.valor, pdf=pdf, usar_ia=usar_ia_iva)
    factura = Factura(
        cufe=doc.cufe,
        prefijo="",
        numero=doc.folio,
        proveedor_id=prov.id,
        fecha_emision=doc.fecha,
        fecha_recepcion=ahora(),
        # el portal no la expone: se deduce del PDF (regex, y IA como último recurso)
        fecha_vencimiento=vencimiento,
        valor_total=doc.valor,
        iva=iva,
        estado_portal=doc.estado_adquiriente,
        estado_proceso="nueva",
        blob_pdf=ruta,
        tipo_documento=tipo_documento,
        texto_pdf=texto,
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
    if venc_por_ia:
        db.add(Evento(factura_id=factura.id, accion="ia_vencimiento",
                      detalle=f"IA dedujo el vencimiento: {vencimiento.date()}"))
    if iva_por_ia:
        db.add(Evento(factura_id=factura.id, accion="ia_iva",
                      detalle=f"IA leyó el IVA: {iva} (base {doc.valor - iva})"))

    reglas.asignar_area(db, factura)
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.flush()
    return factura


def _crear_nota_credito(db: Session, doc: DocumentoPortal, siesa: SiesaClient, almacen) -> NotaCredito:
    """Notas crédito no pasan por el flujo de aprobación: se extraen y se guardan
    para consulta, sin documentos/eventos. Sí se les asigna área con las mismas
    reglas del proveedor (sin IA), para saber a quién corresponde el crédito."""
    prov = _upsert_proveedor(db, doc.nit_emisor, doc.emisor)

    pdf = siesa.descargar_pdf(doc.cufe, doc.fecha, tipo_doc="91")
    ruta = _ruta_blob(doc.nit_emisor, doc.folio, doc.fecha, carpeta="notas_credito")
    almacen.subir(ruta, pdf, content_type="application/pdf")

    nota = NotaCredito(
        cufe=doc.cufe,
        prefijo="",
        numero=doc.folio,
        proveedor_id=prov.id,
        fecha_emision=doc.fecha,
        fecha_recepcion=ahora(),
        valor_total=doc.valor,
        estado_portal=doc.estado_adquiriente,
        blob_pdf=ruta,
        # texto de la nota para evaluar patrones de ítem (reglas de área)
        texto_pdf=extraer_texto(pdf),
    )
    db.add(nota)
    db.flush()

    reglas.asignar_area_nota_credito(db, nota)
    db.flush()
    return nota


def sincronizar(db: Session, dias: int = 3,
                fecha_desde: str | None = None, fecha_hasta: str | None = None,
                limite: int | None = None,
                usar_ia_vencimiento: bool = True,
                usar_ia_iva: bool = True) -> dict:
    """Ejecuta una corrida de ingesta. Devuelve un resumen para n8n/logs.

    limite: si se indica, procesa como máximo esa cantidad de facturas nuevas
    (útil para pruebas y para acotar corridas muy grandes).
    usar_ia_vencimiento: permite que la IA (Haiku) deduzca la fecha de
    vencimiento SOLO en las facturas donde los patrones gratuitos no la
    encontraron. Pasar False para una corrida sin gasto de API.
    usar_ia_iva: igual, pero para el IVA (services/iva_ia.py) — solo cuando la
    reconciliación aritmética gratuita no lo determinó.
    """
    hoy = date.today()
    desde = fecha_desde or (hoy - timedelta(days=dias)).isoformat()
    hasta = fecha_hasta or hoy.isoformat()

    ejec = Ejecucion(inicio=ahora(), estado="en_curso")
    db.add(ejec)
    db.commit()

    almacen = get_almacen()
    nuevas = 0
    notas_credito_nuevas = 0
    errores = 0
    detalles: list[str] = []
    sin_area: list[str] = []

    def _bajo_limite(contador: int) -> bool:
        return limite is None or contador < limite

    try:
        with SiesaClient(settings.url_facturas, settings.username_facturas,
                         settings.password_facturas) as siesa:
            # 1) Facturas
            docs = siesa.listar_documentos(desde, hasta, tipo_doc="1")
            log.info("Portal devolvió %d facturas (%s..%s)", len(docs), desde, hasta)
            for doc in docs:
                if not _bajo_limite(nuevas):
                    log.info("Alcanzado el límite de %d facturas nuevas", limite)
                    break
                if _existe_cufe(db, doc.cufe):
                    continue
                try:
                    f = _crear_factura(db, doc, siesa, almacen, tipo_documento="FACTURA",
                                       usar_ia_vencimiento=usar_ia_vencimiento,
                                       usar_ia_iva=usar_ia_iva)
                    db.commit()
                    nuevas += 1
                    if f.area_id is None:
                        sin_area.append(doc.folio)
                except Exception as e:  # noqa: BLE001 — no abortar toda la corrida por un documento
                    db.rollback()
                    errores += 1
                    detalles.append(f"[Factura] {doc.folio}: {e}")
                    log.exception("Error procesando factura %s", doc.folio)

            # 2) Documentos Equivalentes — fusionados en la misma tabla/flujo que Factura
            docs_eq = siesa.listar_documentos(desde, hasta, tipo_doc="20")
            log.info("Portal devolvió %d documentos equivalentes (%s..%s)", len(docs_eq), desde, hasta)
            for doc in docs_eq:
                if not _bajo_limite(nuevas):
                    log.info("Alcanzado el límite de %d facturas nuevas (incl. equivalentes)", limite)
                    break
                if _existe_cufe(db, doc.cufe):
                    continue
                try:
                    f = _crear_factura(db, doc, siesa, almacen, tipo_documento="EQUIVALENTE",
                                       usar_ia_vencimiento=usar_ia_vencimiento,
                                       usar_ia_iva=usar_ia_iva)
                    db.commit()
                    nuevas += 1
                    if f.area_id is None:
                        sin_area.append(doc.folio)
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    errores += 1
                    detalles.append(f"[Equivalente] {doc.folio}: {e}")
                    log.exception("Error procesando documento equivalente %s", doc.folio)

            # 3) Notas Crédito — módulo separado, sin área/completitud/aprobación
            docs_nc = siesa.listar_documentos(desde, hasta, tipo_doc="91")
            log.info("Portal devolvió %d notas crédito (%s..%s)", len(docs_nc), desde, hasta)
            for doc in docs_nc:
                if not _bajo_limite(notas_credito_nuevas):
                    log.info("Alcanzado el límite de %d notas crédito nuevas", limite)
                    break
                if _existe_cufe_nc(db, doc.cufe):
                    continue
                try:
                    _crear_nota_credito(db, doc, siesa, almacen)
                    db.commit()
                    notas_credito_nuevas += 1
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    errores += 1
                    detalles.append(f"[Nota Crédito] {doc.folio}: {e}")
                    log.exception("Error procesando nota crédito %s", doc.folio)

        ejec.estado = "ok" if errores == 0 else "error"
    except Exception as e:  # noqa: BLE001
        ejec.estado = "error"
        detalles.append(f"Fallo general: {e}")
        log.error("Fallo general de la ingesta:\n%s", traceback.format_exc())
    finally:
        ejec.fin = ahora()
        ejec.facturas_nuevas = nuevas
        ejec.notas_credito_nuevas = notas_credito_nuevas
        ejec.errores = errores
        ejec.detalle = "\n".join(detalles)[:4000] if detalles else None
        db.commit()

    return {
        "ejecucion_id": ejec.id,
        "estado": ejec.estado,
        "rango": {"desde": desde, "hasta": hasta},
        "facturas_nuevas": nuevas,
        "notas_credito_nuevas": notas_credito_nuevas,
        "errores": errores,
        "sin_area_asignada": sin_area,
        "detalle": detalles,
    }
