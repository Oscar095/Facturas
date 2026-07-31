"""Prueba del módulo "Cargar factura" (carga manual con IA) contra la API real.

1. Genera un PDF sintético con texto de factura y lo pasa por /carga/extraer
   (llamada REAL a Claude Haiku — barata; verifica que la IA lea los campos).
2. Crea la factura por /carga con datos explícitos (independiente de la IA),
   y verifica: detalle, origen=manual, documento FV, evento carga_manual,
   PDF servido por la API y dedup (segundo intento -> 409).
3. Limpia todo (factura, documentos, eventos, proveedor sintético y blob).
"""
import sys

sys.path.insert(0, "backend")
from io import BytesIO

import httpx
from reportlab.pdfgen import canvas as rl_canvas
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Documento, Evento, Factura, Proveedor
from app.services.blob_storage import get_almacen

BASE = "http://127.0.0.1:8000"
NIT = "900777666"
NUMERO = "TCM-77"

buf = BytesIO()
c = rl_canvas.Canvas(buf, pagesize=(612, 792))
lineas = [
    "FACTURA ELECTRONICA DE VENTA No. TCM-77",
    "Emisor: PROVEEDOR PRUEBA CARGA MANUAL S.A.S.",
    "NIT: 900.777.666-1",
    "Fecha de emision: 2026-07-15",
    "Cliente: KOS COLOMBIA",
    "Concepto: servicio de mantenimiento de prueba",
    "Subtotal: 1.000.000    IVA (19%): 190.000",
    "TOTAL A PAGAR: $1.190.000",
]
for i, linea in enumerate(lineas):
    c.drawString(72, 720 - i * 24, linea)
c.showPage()
c.save()
PDF = buf.getvalue()

cl = httpx.Client(base_url=BASE, timeout=120)
r = cl.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
cl.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

factura_id = None
try:
    # 1) extracción con IA (real)
    r = cl.post("/api/facturas/carga/extraer", files={"archivo": ("prueba.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    ext = r.json()
    print(f"1) extracción IA -> {ext}")
    assert ext["nit"] == NIT, f"NIT extraído mal: {ext['nit']}"
    assert ext["numero"] and "TCM-77" in ext["numero"], f"número extraído mal: {ext['numero']}"
    assert ext["fecha_emision"] == "2026-07-15", f"fecha extraída mal: {ext['fecha_emision']}"
    assert float(ext["valor_total"]) == 1190000, f"valor extraído mal: {ext['valor_total']}"
    print("1) la IA extrajo NIT, número, fecha y valor correctos: OK")

    # 2) archivo no-PDF rechazado
    r = cl.post("/api/facturas/carga/extraer", files={"archivo": ("x.pdf", b"no soy pdf", "application/pdf")})
    assert r.status_code == 400, r.text
    print("2) archivo que no es PDF rechazado (400): OK")

    # 3) crear la factura (datos explícitos, sin depender de la IA)
    datos = {"nit": NIT, "razon_social": "PROVEEDOR PRUEBA CARGA MANUAL S.A.S.",
             "numero": NUMERO, "fecha_emision": "2026-07-15",
             "valor_total": "1190000", "iva": "190000"}
    r = cl.post("/api/facturas/carga", data=datos,
                files={"archivo": ("prueba.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    f = r.json()
    factura_id = f["id"]
    assert f["origen"] == "manual" and f["numero"] == NUMERO and f["cufe"] is None
    assert f["proveedor"]["nit"] == NIT
    assert any(d["tipo"] == "FV" for d in f["documentos"]), "sin documento FV"
    print(f"3) factura manual creada id={factura_id} (origen=manual, FV adjunta): OK")

    # 4) el PDF se sirve por la API y el evento quedó auditado
    r = cl.get(f"/api/facturas/{factura_id}/pdf")
    assert r.status_code == 200 and r.content == PDF
    db = SessionLocal()
    ev = db.execute(select(Evento).where(
        Evento.factura_id == factura_id, Evento.accion == "carga_manual")).scalar_one()
    assert "Cargada manualmente" in ev.detalle
    tiene_texto = bool(db.get(Factura, factura_id).texto_pdf)
    db.close()
    assert tiene_texto, "texto_pdf vacío (necesario para reglas de área)"
    print("4) PDF servido por la API, evento carga_manual y texto_pdf poblado: OK")

    # 5) dedup: mismo proveedor + número -> 409
    r = cl.post("/api/facturas/carga", data=datos,
                files={"archivo": ("prueba.pdf", PDF, "application/pdf")})
    assert r.status_code == 409, r.text
    print(f"5) duplicado rechazado (409: {r.json()['detail']}): OK")
finally:
    db = SessionLocal()
    if factura_id:
        db.query(Evento).filter(Evento.factura_id == factura_id).delete()
        db.query(Documento).filter(Documento.factura_id == factura_id).delete()
        fx = db.get(Factura, factura_id)
        blob = fx.blob_pdf
        db.delete(fx)
        db.commit()
        if blob:
            get_almacen().eliminar(blob)
    prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
    if prov and not db.execute(select(Factura).where(Factura.proveedor_id == prov.id)).first():
        db.delete(prov)
        db.commit()
    db.close()
    print("6) limpieza (factura, blob y proveedor sintético): OK")
