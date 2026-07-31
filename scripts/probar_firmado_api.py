"""Prueba del firmado al aprobar, sobre una factura SINTÉTICA:
se firma TODO documento PDF sin importar su tipo (FV y también OTRO);
CRN (.txt) se omite solo por no ser PDF. Verifica sello en TODAS las
páginas (texto + imagen), rutas nuevas y eventos. Crea su propia firma
de prueba y limpia todo al final."""
import sys
sys.path.insert(0, "backend")
from io import BytesIO
import httpx
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas as rl_canvas
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, Documento, Evento, Factura, Proveedor, ahora
from app.services.blob_storage import get_almacen

BASE = "http://127.0.0.1:8000"
almacen = get_almacen()

# ── firma PNG (transparente, con trazo visible) ──
img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.line([(20, 100), (80, 40), (140, 110), (200, 50), (260, 100), (340, 60)],
       fill=(25, 35, 95, 255), width=6)
buf_png = BytesIO(); img.save(buf_png, "PNG"); PNG_FIRMA = buf_png.getvalue()

# ── FV: PDF de 2 páginas ──
def pdf_prueba(paginas=2):
    b = BytesIO()
    c = rl_canvas.Canvas(b, pagesize=(612, 792))
    for i in range(paginas):
        c.drawString(72, 720, f"FACTURA DE PRUEBA - pagina {i+1}")
        c.showPage()
    c.save()
    return b.getvalue()

# ── montar factura sintética procesada con FV + CRN(.txt) + OTRO(pdf) ──
db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
almacen.subir("prueba_firma/fv.pdf", pdf_prueba(), content_type="application/pdf")
almacen.subir("prueba_firma/crn.txt", b"recepcion de mercancia", content_type="text/plain")
almacen.subir("prueba_firma/otro.pdf", pdf_prueba(1), content_type="application/pdf")
f = Factura(cufe="TEST-FIRMADO", prefijo="", numero="TEST-FIRMA-1", proveedor_id=prov.id,
            fecha_recepcion=ahora(), estado_proceso="procesada", area_id=area.id,
            blob_pdf="prueba_firma/fv.pdf")
db.add(f); db.flush()
fid = f.id
db.add(Documento(factura_id=fid, tipo="FV", blob_path="prueba_firma/fv.pdf", nombre_archivo="fv.pdf"))
db.add(Documento(factura_id=fid, tipo="CRN", blob_path="prueba_firma/crn.txt", nombre_archivo="crn.txt"))
db.add(Documento(factura_id=fid, tipo="OTRO", blob_path="prueba_firma/otro.pdf", nombre_archivo="otro.pdf"))
db.commit()
print(f"factura sintética id={fid}")

c = httpx.Client(base_url=BASE, timeout=60)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

firma_id = None
try:
    # subir firma de prueba propia
    r = c.post("/api/firmas", files={"archivo": ("firma_test.png", PNG_FIRMA, "image/png")},
               data={"nombre": "Firma prueba flujo"})
    firma_id = r.json()["id"]

    # firma inexistente -> 404
    r = c.post(f"/api/facturas/{fid}/aprobar", json={"firma_id": 999999})
    assert r.status_code == 404, r.text
    print("1) firma ajena/inexistente rechazada (404): OK")

    # aprobar con la firma propia
    r = c.post(f"/api/facturas/{fid}/aprobar", json={"firma_id": firma_id})
    assert r.status_code == 200, r.text
    assert r.json()["estado_proceso"] == "aprobada"
    print("2) aprobada con firma: OK")

    db2 = SessionLocal()
    docs = {d.tipo: d for d in db2.execute(select(Documento).where(Documento.factura_id == fid)).scalars()}
    fx = db2.get(Factura, fid)
    assert docs["FV"].blob_path == "prueba_firma/fv_firmado.pdf", docs["FV"].blob_path
    assert fx.blob_pdf == "prueba_firma/fv_firmado.pdf", "factura.blob_pdf no se actualizó"
    assert docs["CRN"].blob_path == "prueba_firma/crn.txt", "CRN (.txt) no debía firmarse"
    assert docs["OTRO"].blob_path == "prueba_firma/otro_firmado.pdf", \
        f"OTRO es PDF y ahora debe firmarse también: {docs['OTRO'].blob_path}"
    print("3) FV y OTRO apuntan a PDF firmado (cualquier tipo se firma); CRN (.txt) intacto: OK")

    sellado = almacen.descargar("prueba_firma/fv_firmado.pdf")
    lector = PdfReader(BytesIO(sellado))
    assert len(lector.pages) == 2, "cambió el número de páginas"
    for i, pagina in enumerate(lector.pages):
        t = pagina.extract_text() or ""
        assert "Aprobado por" in t, f"no hay sello en la página {i + 1}: {t!r}"
        assert "/XObject" in pagina.get("/Resources", {}), f"sin imagen de firma en página {i + 1}"
    print("4) sello (imagen + 'Aprobado por') en TODAS las páginas: OK")

    # el documento firmado se sirve por la API
    doc_fv = docs["FV"]
    r = c.get(f"/api/facturas/documento/{doc_fv.id}/archivo")
    assert r.status_code == 200 and r.content == sellado
    print("5) el PDF firmado se descarga por la API: OK")

    ev = [e.detalle for e in db2.execute(select(Evento).where(
        Evento.factura_id == fid, Evento.accion == "aprobada")).scalars()][0]
    assert "FV" in ev and "OTRO" in ev and "CRN (no es PDF)" in ev
    print(f"6) evento auditado (FV y OTRO firmados, CRN omitido por no-PDF): {ev!r}: OK")
    db2.close()
finally:
    db3 = SessionLocal()
    db3.query(Evento).filter(Evento.factura_id == fid).delete()
    for dcc in db3.query(Documento).filter(Documento.factura_id == fid).all():
        db3.delete(dcc)
    fx = db3.get(Factura, fid)
    db3.delete(fx); db3.commit(); db3.close()
    for rta in ("prueba_firma/fv.pdf", "prueba_firma/fv_firmado.pdf",
                "prueba_firma/crn.txt", "prueba_firma/otro.pdf",
                "prueba_firma/otro_firmado.pdf"):
        almacen.eliminar(rta)
    if firma_id:
        c.delete(f"/api/firmas/{firma_id}")
    print("7) limpieza (factura, blobs y firma de prueba): OK")
