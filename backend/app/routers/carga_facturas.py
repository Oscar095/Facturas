"""Carga manual de facturas (módulo "Cargar factura").

El ~80% de las facturas llega por el robot del portal Siesa; el resto llega
físico o por correo. Aquí el usuario sube el PDF, la IA (Claude) pre-llena los
datos, el usuario los REVISA/corrige en el formulario y al confirmar la factura
entra a la MISMA tabla y flujo que las del portal (proveedor, blob, documento
FV, evento, reglas de área y completitud), marcada con origen='manual'.

Dos pasos (el backend no guarda nada entre uno y otro; el PDF viaja en ambos):
  POST /api/facturas/carga/extraer  -> solo lee el PDF con IA, no escribe nada.
  POST /api/facturas/carga          -> crea la factura con los datos revisados.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Documento, Evento, Factura, Proveedor, Usuario, ahora
from ..schemas import ExtraccionFactura, FacturaDetalle
from ..security import requiere_permiso
from ..services import extraer_factura, reglas
from ..services.blob_storage import get_almacen
from ..services.pdf_texto import extraer_texto

router = APIRouter(prefix="/api/facturas/carga", tags=["carga manual"])

_MAX_PDF = 20 * 1024 * 1024  # 20 MB


async def _leer_pdf(archivo: UploadFile) -> bytes:
    datos = await archivo.read()
    if len(datos) > _MAX_PDF:
        raise HTTPException(413, "El PDF supera el máximo de 20 MB")
    if not datos.startswith(b"%PDF"):
        raise HTTPException(400, "El archivo debe ser un PDF")
    return datos


@router.post("/extraer", response_model=ExtraccionFactura)
async def extraer(archivo: UploadFile = File(...),
                  usuario: Usuario = Depends(requiere_permiso("editar_facturas"))):
    """Lee el PDF con IA y devuelve los datos para pre-llenar el formulario.

    Nunca falla por culpa de la IA: si no puede leer la factura, devuelve el
    formulario vacío con la advertencia y el usuario lo llena a mano.
    """
    pdf = await _leer_pdf(archivo)
    texto = extraer_texto(pdf)

    advertencias: list[str] = []
    datos: dict = {}
    try:
        datos = extraer_factura.extraer_datos(pdf, texto)
    except RuntimeError as e:
        advertencias.append(str(e))

    salida = ExtraccionFactura(advertencias=advertencias)
    if datos.get("nit"):
        salida.nit = str(datos["nit"])[:30]
    if datos.get("razon_social"):
        salida.razon_social = str(datos["razon_social"])[:300]
    if datos.get("numero"):
        salida.numero = str(datos["numero"])[:40]
    if datos.get("cufe"):
        salida.cufe = str(datos["cufe"])[:120]
    for campo in ("fecha_emision", "fecha_vencimiento"):
        if datos.get(campo):
            try:
                setattr(salida, campo, date.fromisoformat(str(datos[campo])))
            except ValueError:
                advertencias.append(f"Fecha ilegible en {campo}: {datos[campo]}")
    for campo in ("valor_total", "iva", "trm"):
        if datos.get(campo) is not None:
            try:
                setattr(salida, campo, Decimal(str(datos[campo])))
            except InvalidOperation:
                advertencias.append(f"Valor ilegible en {campo}: {datos[campo]}")
    if datos.get("moneda"):
        salida.moneda = "USD" if str(datos["moneda"]).upper() == "USD" else "COP"

    if datos:
        faltaron = [c for c in ("nit", "razon_social", "numero") if not datos.get(c)]
        if faltaron:
            advertencias.append(
                "La IA no encontró: " + ", ".join(faltaron) + " — complétalos a mano"
            )
        if salida.moneda == "USD" and salida.trm is None:
            advertencias.append(
                "Factura en USD sin TRM visible en el PDF — diligencia la tasa de "
                "cambio para guardar los valores en pesos"
            )
    return salida


@router.post("", response_model=FacturaDetalle)
async def crear(
    archivo: UploadFile = File(...),
    nit: str = Form(...),
    razon_social: str = Form(...),
    numero: str = Form(...),
    cufe: str | None = Form(None),
    fecha_emision: date | None = Form(None),
    fecha_vencimiento: date | None = Form(None),
    valor_total: Decimal | None = Form(None),
    iva: Decimal | None = Form(None),
    moneda: str = Form("COP"),
    trm: Decimal | None = Form(None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(requiere_permiso("editar_facturas")),
):
    """Crea la factura manual con los datos ya revisados por el usuario.

    Si moneda=USD, valor_total/iva llegan en dólares y aquí se convierten a COP
    con la TRM (obligatoria en ese caso): la BD guarda SIEMPRE pesos; el valor
    en dólares queda en valor_original y la tasa usada en trm.
    """
    pdf = await _leer_pdf(archivo)

    moneda = (moneda or "COP").strip().upper()
    if moneda not in ("COP", "USD"):
        raise HTTPException(400, "Moneda no soportada (solo COP o USD)")
    valor_original = None
    if moneda == "USD":
        if not trm or trm <= 0:
            raise HTTPException(400, "Para facturas en USD la TRM es obligatoria")
        valor_original = valor_total
        centavos = Decimal("0.01")
        if valor_total is not None:
            valor_total = (valor_total * trm).quantize(centavos)
        if iva is not None:
            iva = (iva * trm).quantize(centavos)
    else:
        trm = None

    nit = "".join(c for c in nit.split("-")[0] if c.isdigit())
    numero = numero.strip()
    razon_social = razon_social.strip()
    cufe = (cufe or "").strip() or None
    if not nit or not numero or not razon_social:
        raise HTTPException(400, "NIT, razón social y número de factura son obligatorios")

    # Dedup: mismo criterio que la ingesta del portal (CUFE y proveedor+folio)
    if cufe:
        dup = db.execute(select(Factura).where(Factura.cufe == cufe)).scalar_one_or_none()
        if dup:
            raise HTTPException(409, f"Ya existe una factura con ese CUFE (folio {dup.numero})")
    prov = db.execute(select(Proveedor).where(Proveedor.nit == nit)).scalar_one_or_none()
    if prov:
        dup = db.execute(select(Factura).where(
            Factura.proveedor_id == prov.id, Factura.prefijo == "", Factura.numero == numero
        )).scalar_one_or_none()
        if dup:
            raise HTTPException(409, f"Ya existe la factura {numero} de ese proveedor")
    else:
        prov = Proveedor(nit=nit, razon_social=razon_social)
        db.add(prov)
        db.flush()

    fecha_dt = datetime.combine(fecha_emision, time()) if fecha_emision else None
    folio_limpio = "".join(c for c in numero if c.isalnum() or c in "-_") or "sin_folio"
    f = fecha_dt or datetime.utcnow()
    ruta = f"facturas/{f.year:04d}/{f.month:02d}/{nit}_{folio_limpio}.pdf"
    get_almacen().subir(ruta, pdf, content_type="application/pdf")

    factura = Factura(
        cufe=cufe,
        prefijo="",
        numero=numero,
        proveedor_id=prov.id,
        fecha_emision=fecha_dt,
        fecha_recepcion=ahora(),
        fecha_vencimiento=(datetime.combine(fecha_vencimiento, time())
                           if fecha_vencimiento else None),
        valor_total=valor_total,
        iva=iva,
        moneda=moneda,
        trm=trm,
        valor_original=valor_original,
        estado_proceso="nueva",
        blob_pdf=ruta,
        tipo_documento="FACTURA",
        origen="manual",
        texto_pdf=extraer_texto(pdf),
    )
    db.add(factura)
    db.flush()

    db.add(Documento(
        factura_id=factura.id,
        tipo="FV",
        blob_path=ruta,
        nombre_archivo=f"{nit}_{folio_limpio}.pdf",
        subido_por_id=usuario.id,
    ))
    detalle_evento = f"Cargada manualmente por {usuario.nombre} ({archivo.filename})"
    if moneda == "USD":
        detalle_evento += f" — USD {valor_original} convertido a COP con TRM {trm}"
    db.add(Evento(factura_id=factura.id, usuario_id=usuario.id, accion="carga_manual",
                  detalle=detalle_evento))

    reglas.asignar_area(db, factura)
    db.flush()
    reglas.evaluar_completitud(db, factura)
    db.commit()
    db.refresh(factura)

    salida = FacturaDetalle.model_validate(factura)
    salida.faltantes = reglas.faltan_documentos(db, factura)
    return salida
