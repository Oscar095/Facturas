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
rollback de ese documento y continúa con los demás, y un fallo de una FASE
(p. ej. el listado de equivalentes) no impide correr las siguientes.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Documento, Ejecucion, Evento, Factura, NotaCredito, Proveedor, ahora
from ..services import reglas
from ..services.blob_storage import get_almacen
from ..services.pdf_texto import extraer_texto
from ..services.iva import resolver_iva, subtotal
from ..services.vencimiento import resolver_vencimiento
from .siesa_client import (CredencialesRechazadas, DocumentoPortal, DocumentoSinPdf,
                           SesionPerdida, SiesaClient)

log = logging.getLogger("ingesta")


class _CorridaAbortada(RuntimeError):
    """No tiene sentido seguir en esta corrida (p. ej. la sesión se perdió dos veces)."""


# Cuántas veces por corrida se vuelve a entrar al portal tras una SesionPerdida.
_MAX_RECONEXIONES = 1

# Va en el 'Fallo general' de una corrida cuyo login rechazó el portal. Las
# corridas automáticas siguientes no vuelven a probar la MISMA clave (cada
# intento acerca la cuenta al bloqueo); ver _clave_ya_rechazada.
_MARCA_RECHAZO = "[clave rechazada {}]"


@dataclass(frozen=True)
class _Fase:
    etiqueta: str                 # como aparece en ejecuciones.detalle
    tipo_doc: str                 # filtro tipoDocRecepcion del portal
    tipo_documento: str | None    # facturas.tipo_documento; None = va a notas_credito


_FASES = (
    _Fase("Factura", "1", "FACTURA"),
    _Fase("Equivalente", "20", "EQUIVALENTE"),
    _Fase("Nota Crédito", "91", None),
    # Nota (crédito) a un Documento Equivalente: p. ej. Copa anula tiquetes ya
    # cargados como equivalentes. Va a notas_credito para que netee el gasto.
    _Fase("Nota Equivalente", "94", None),
)


@dataclass
class _Corrida:
    """Contadores y bitácora de una corrida."""

    facturas_nuevas: int = 0          # incluye los equivalentes (misma tabla)
    notas_credito_nuevas: int = 0
    errores: int = 0
    fases: list[str] = field(default_factory=list)      # una línea por fase
    sin_pdf: list[str] = field(default_factory=list)    # el portal no tiene su PDF
    detalles: list[str] = field(default_factory=list)   # un error por línea
    sin_area: list[str] = field(default_factory=list)
    reconexiones: int = 0


def _primera_linea(e: BaseException, largo: int = 300) -> str:
    """Primera línea del error. Los de Playwright traen decenas de líneas de
    'Call log': con 4 errores se llenaban los 4000 caracteres del detalle y el
    'Fallo general' del final —lo más importante— quedaba cortado."""
    lineas = str(e).strip().splitlines()
    return (lineas[0] if lineas else type(e).__name__)[:largo]


def _huella_credencial() -> str:
    """Huella corta de usuario+clave (HMAC con JWT_SECRET): dice si la clave
    configurada es la MISMA que el portal ya rechazó, sin guardar la clave."""
    msg = f"{settings.username_facturas}\0{settings.password_facturas}".encode()
    return hmac.new(settings.jwt_secret.encode(), msg, hashlib.sha256).hexdigest()[:12]


def _clave_ya_rechazada(db: Session, ejec_id: int, huella: str) -> Ejecucion | None:
    """La última corrida terminada, si el portal le rechazó ESTA misma clave.

    El 2026-11-19 la cuenta del robot quedó bloqueada; con la clave vieja en
    los App Settings cada corrida automática (2 al día + reintentos) habría
    sumado un intento fallido más. Se vuelve a probar sola cuando cambia la
    clave (cambia la huella), o a mano con 'Sincronizar ahora' (forzar_login).
    """
    previa = db.execute(
        select(Ejecucion).where(Ejecucion.id != ejec_id, Ejecucion.fin.isnot(None))
        .order_by(Ejecucion.id.desc()).limit(1)
    ).scalar_one_or_none()
    if previa is not None and previa.detalle and _MARCA_RECHAZO.format(huella) in previa.detalle:
        return previa
    return None


def _reconectar(siesa: SiesaClient, corrida: _Corrida, motivo: Exception) -> None:
    """Vuelve a entrar al portal tras una SesionPerdida (una vez por corrida)."""
    if corrida.reconexiones >= _MAX_RECONEXIONES:
        raise _CorridaAbortada(
            f"Se perdió otra vez la sesión del portal: {_primera_linea(motivo)}") from motivo
    corrida.reconexiones += 1
    log.warning("Sesión del portal perdida (%s); se vuelve a entrar", _primera_linea(motivo))
    try:
        siesa.reiniciar_sesion()
    except CredencialesRechazadas:
        raise
    except Exception as e:  # noqa: BLE001
        raise _CorridaAbortada(
            f"Se perdió la sesión del portal y no se pudo volver a entrar: {_primera_linea(e)}"
        ) from e


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
                      detalle=f"IA leyó el IVA: {iva} (base {subtotal(doc.valor, iva)})"))

    reglas.asignar_area(db, factura)
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.flush()
    return factura


def _crear_nota_credito(db: Session, doc: DocumentoPortal, siesa: SiesaClient, almacen,
                        usar_ia_iva: bool = False, tipo_doc: str = "91") -> NotaCredito:
    """Notas crédito no pasan por el flujo de aprobación: se extraen y se guardan
    para consulta, sin documentos/eventos. Sí se les asigna área con las mismas
    reglas del proveedor (sin IA), para saber a quién corresponde el crédito."""
    prov = _upsert_proveedor(db, doc.nit_emisor, doc.emisor)

    pdf = siesa.descargar_pdf(doc.cufe, doc.fecha, tipo_doc=tipo_doc)
    ruta = _ruta_blob(doc.nit_emisor, doc.folio, doc.fecha, carpeta="notas_credito")
    almacen.subir(ruta, pdf, content_type="application/pdf")

    # texto de la nota para evaluar patrones de ítem (reglas de área) y deducir el IVA
    texto = extraer_texto(pdf)
    # El panel netea las notas crédito contra lo facturado y todo se mide SIN IVA:
    # una nota con el IVA incluido restaría de más. Misma cascada que las facturas.
    # (A diferencia de la factura no queda evento: eventos.factura_id es NOT NULL
    # contra facturas, así que una nota crédito no puede auditarse ahí.)
    iva, _ = resolver_iva(texto, doc.valor, pdf=pdf, usar_ia=usar_ia_iva)

    nota = NotaCredito(
        cufe=doc.cufe,
        prefijo="",
        numero=doc.folio,
        proveedor_id=prov.id,
        fecha_emision=doc.fecha,
        fecha_recepcion=ahora(),
        valor_total=doc.valor,
        iva=iva,
        estado_portal=doc.estado_adquiriente,
        blob_pdf=ruta,
        texto_pdf=texto,
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
                usar_ia_iva: bool = True,
                forzar_login: bool = False) -> dict:
    """Ejecuta una corrida de ingesta. Devuelve un resumen para n8n/logs.

    limite: si se indica, procesa como máximo esa cantidad de facturas nuevas
    (útil para pruebas y para acotar corridas muy grandes).
    usar_ia_vencimiento: permite que la IA (Haiku) deduzca la fecha de
    vencimiento SOLO en las facturas donde los patrones gratuitos no la
    encontraron. Pasar False para una corrida sin gasto de API.
    usar_ia_iva: igual, pero para el IVA (services/iva_ia.py) — solo cuando la
    reconciliación aritmética gratuita no lo determinó. Solo aplica a las
    facturas: las notas crédito deducen su IVA únicamente por la vía gratis.
    forzar_login: entrar al portal aunque la corrida anterior haya visto
    rechazada esta misma clave (lo usa 'Sincronizar ahora': hay una persona
    mirando, p. ej. tras desbloquear la cuenta sin cambiar la clave).
    """
    hoy = date.today()
    desde = fecha_desde or (hoy - timedelta(days=dias)).isoformat()
    hasta = fecha_hasta or hoy.isoformat()

    ejec = Ejecucion(inicio=ahora(), estado="en_curso")
    db.add(ejec)
    db.commit()

    almacen = get_almacen()
    corrida = _Corrida()
    fallo_general: str | None = None
    huella = _huella_credencial()

    try:
        previa = None if forzar_login else _clave_ya_rechazada(db, ejec.id, huella)
        if previa is not None:
            raise CredencialesRechazadas(
                f"No se intentó entrar al portal: ya rechazó esta misma clave en la corrida "
                f"#{previa.id} ({previa.inicio:%Y-%m-%d %H:%M} UTC). Actualizar "
                "PASSWORD_FACTURAS (.env y App Settings) o usar 'Sincronizar ahora' en el Admin."
            )
        with SiesaClient(settings.url_facturas, settings.username_facturas,
                         settings.password_facturas) as siesa:
            for fase in _FASES:
                _correr_fase(db, siesa, almacen, fase, desde, hasta, corrida, limite,
                             usar_ia_vencimiento, usar_ia_iva)
        ejec.estado = "ok" if corrida.errores == 0 else "error"
    except Exception as e:  # noqa: BLE001
        try:
            db.rollback()  # lo que quedara a medias de un documento no se guarda
        except Exception:  # noqa: BLE001 — la conexión pudo ser la causa
            log.exception("No se pudo hacer rollback tras el fallo general")
        ejec.estado = "error"
        # que cuente: errores=0 con estado 'error' no disparaba ninguna alerta
        corrida.errores += 1
        fallo_general = f"Fallo general: {_primera_linea(e, 600)}"
        if isinstance(e, CredencialesRechazadas):
            fallo_general += " " + _MARCA_RECHAZO.format(huella)
        log.error("Fallo general de la ingesta:\n%s", traceback.format_exc())
    finally:
        ejec.fin = ahora()
        ejec.facturas_nuevas = corrida.facturas_nuevas
        ejec.notas_credito_nuevas = corrida.notas_credito_nuevas
        ejec.errores = corrida.errores
        ejec.detalle = _armar_detalle(desde, hasta, fallo_general, corrida)
        db.commit()

    return {
        "ejecucion_id": ejec.id,
        "estado": ejec.estado,
        "rango": {"desde": desde, "hasta": hasta},
        "facturas_nuevas": corrida.facturas_nuevas,
        "notas_credito_nuevas": corrida.notas_credito_nuevas,
        "errores": corrida.errores,
        "sin_area_asignada": corrida.sin_area,
        "sin_pdf": corrida.sin_pdf,
        "fases": corrida.fases,
        "detalle": ([fallo_general] if fallo_general else []) + corrida.detalles,
    }


def _correr_fase(db: Session, siesa: SiesaClient, almacen, fase: _Fase, desde: str,
                 hasta: str, corrida: _Corrida, limite: int | None,
                 usar_ia_vencimiento: bool, usar_ia_iva: bool) -> None:
    """Lista un tipo de documento y crea los que falten. Un fallo de la fase
    queda anotado y la corrida sigue con la siguiente.

    Antes las tres fases iban en un solo try: si el listado de equivalentes
    fallaba (un popup del portal tapaba el botón Buscar), la excepción subía
    hasta el 'Fallo general' y las notas crédito ni se pedían. Así se dejaron de
    traer equivalentes y notas crédito del 2026-11-06 al 2026-11-20.
    """
    es_nota = fase.tipo_documento is None
    try:
        try:
            docs = siesa.listar_documentos(desde, hasta, tipo_doc=fase.tipo_doc)
        except SesionPerdida as e:
            _reconectar(siesa, corrida, e)
            docs = siesa.listar_documentos(desde, hasta, tipo_doc=fase.tipo_doc)
    except (CredencialesRechazadas, _CorridaAbortada):
        raise
    except Exception as e:  # noqa: BLE001
        corrida.errores += 1
        corrida.fases.append(f"{fase.etiqueta}: NO SE PUDO LISTAR ({_primera_linea(e)})")
        log.exception("No se pudo listar %s", fase.etiqueta)
        return
    total_portal = siesa.ultimo_total
    log.info("Portal devolvió %d de tipo %s (%s..%s; reporta %d)", len(docs), fase.etiqueta,
             desde, hasta, total_portal)

    nuevas = sin_pdf = errores = 0
    try:
        for doc in docs:
            contador = corrida.notas_credito_nuevas if es_nota else corrida.facturas_nuevas
            if limite is not None and contador >= limite:
                log.info("Alcanzado el límite de %d documentos nuevos (%s)", limite, fase.etiqueta)
                break
            if (_existe_cufe_nc if es_nota else _existe_cufe)(db, doc.cufe):
                continue
            try:
                if es_nota:
                    # Sin IA a propósito (regla de negocio: no se gastan créditos
                    # de Claude en notas crédito). La vía gratis resuelve el 93%
                    # de las históricas, y sobre las 2 que no, la IA tampoco pudo:
                    # su respuesta no reconcilió con el total y quedaron en NULL.
                    _crear_nota_credito(db, doc, siesa, almacen, usar_ia_iva=False,
                                        tipo_doc=fase.tipo_doc)
                    db.commit()
                    corrida.notas_credito_nuevas += 1
                else:
                    f = _crear_factura(db, doc, siesa, almacen,
                                       tipo_documento=fase.tipo_documento,
                                       usar_ia_vencimiento=usar_ia_vencimiento,
                                       usar_ia_iva=usar_ia_iva)
                    db.commit()
                    corrida.facturas_nuevas += 1
                    if f.area_id is None:
                        corrida.sin_area.append(doc.folio)
                nuevas += 1
            except DocumentoSinPdf:
                # El proveedor mandó el XML sin PDF: no es una falla del robot. Se
                # anota aparte (no cuenta como error) y se vuelve a mirar en la
                # próxima corrida, por si el portal llega a tenerlo.
                db.rollback()
                sin_pdf += 1
                corrida.sin_pdf.append(f"{fase.etiqueta} {doc.folio}")
            except SesionPerdida as e:
                # el documento se pierde en esta corrida (vuelve en la próxima)
                db.rollback()
                errores += 1
                corrida.errores += 1
                corrida.detalles.append(f"[{fase.etiqueta}] {doc.folio}: {_primera_linea(e)}")
                _reconectar(siesa, corrida, e)
            except Exception as e:  # noqa: BLE001 — no abortar toda la corrida por un documento
                db.rollback()
                errores += 1
                corrida.errores += 1
                corrida.detalles.append(f"[{fase.etiqueta}] {doc.folio}: {_primera_linea(e)}")
                log.exception("Error procesando %s %s", fase.etiqueta, doc.folio)
    except (CredencialesRechazadas, _CorridaAbortada):
        raise
    except Exception as e:  # noqa: BLE001 — p. ej. se cayó la conexión a la BD
        db.rollback()
        corrida.errores += 1
        corrida.fases.append(f"{fase.etiqueta}: INTERRUMPIDA tras {nuevas} nuevas "
                             f"({_primera_linea(e)})")
        log.exception("Fase %s interrumpida", fase.etiqueta)
        return

    linea = f"{fase.etiqueta}: {len(docs)} en el portal, {nuevas} nuevas"
    if sin_pdf:
        linea += f", {sin_pdf} sin PDF"
    if errores:
        linea += f", {errores} con error"
    if len(docs) < total_portal:
        # el portal reporta más de los que se alcanzaron a leer: lo que falta no
        # se procesó, y que la corrida diga 'ok' lo escondería
        corrida.errores += 1
        linea += f", LISTADO INCOMPLETO (se leyeron {len(docs)} de {total_portal})"
    corrida.fases.append(linea)


def _armar_detalle(desde: str, hasta: str, fallo_general: str | None,
                   corrida: _Corrida) -> str:
    """Lo importante va PRIMERO (fallo general, una línea por fase, los sin PDF,
    el rango) y al final los errores por documento: el corte a 4000 caracteres
    solo puede comerse la cola de esa lista, nunca el resumen. Y la celda del
    Admin muestra solo el comienzo: ahí tiene que estar el problema."""
    lineas = [fallo_general] if fallo_general else []
    lineas += corrida.fases
    if corrida.sin_pdf:
        lineas.append("Sin PDF en el portal (el proveedor no lo envió; se reintenta en "
                      "cada corrida): " + ", ".join(corrida.sin_pdf))
    lineas.append(f"Rango {desde}..{hasta}")
    lineas += corrida.detalles
    return "\n".join(lineas)[:4000]
