"""UI: aprobar con firma desde el detalle — panel con selector, firmar, badge Aprobada."""
import sys
sys.path.insert(0, "backend")
from io import BytesIO
import httpx
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright, expect
from reportlab.pdfgen import canvas as rl_canvas
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Area, Documento, Evento, Factura, Proveedor, ahora
from app.services.blob_storage import get_almacen

almacen = get_almacen()
img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
ImageDraw.Draw(img).line([(20, 100), (140, 40), (260, 100), (340, 55)], fill=(25, 35, 95, 255), width=6)
b = BytesIO(); img.save(b, "PNG"); PNG_FIRMA = b.getvalue()

pb = BytesIO(); cnv = rl_canvas.Canvas(pb, pagesize=(612, 792))
cnv.drawString(72, 720, "FV UI"); cnv.save()

db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
almacen.subir("prueba_firma_ui/fv.pdf", pb.getvalue(), content_type="application/pdf")
f = Factura(cufe="TEST-UI-FIRMA", prefijo="", numero="TEST-UI-F1", proveedor_id=prov.id,
            fecha_recepcion=ahora(), estado_proceso="procesada", area_id=area.id,
            blob_pdf="prueba_firma_ui/fv.pdf")
db.add(f); db.flush()
fid = f.id
db.add(Documento(factura_id=fid, tipo="FV", blob_path="prueba_firma_ui/fv.pdf", nombre_archivo="fv.pdf"))
db.commit()

c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
r = c.post("/api/auth/login", data={"username": "oscar.orozco03@gmail.com", "password": "Admin1234*"})
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
firma_id = c.post("/api/firmas", files={"archivo": ("f_ui.png", PNG_FIRMA, "image/png")},
                  data={"nombre": "Firma prueba UI"}).json()["id"]

errores = []
try:
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_context().new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(str(e)))

        page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
        page.fill("input[type=email]", "oscar.orozco03@gmail.com")
        page.fill("input[type=password]", "Admin1234*")
        page.click("button:has-text('Ingresar')")
        page.wait_for_selector(".sidebar", timeout=15000)

        page.goto(f"http://127.0.0.1:8000/facturas/{fid}", wait_until="networkidle")
        page.wait_for_selector("h1:has-text('TEST-UI-F1')", timeout=8000)

        page.click("button:has-text('Aprobar factura')")
        panel = page.locator(".aprobar-panel")
        expect(panel).to_be_visible(timeout=5000)
        print("1) panel de firma abierto: OK")

        panel.locator("select").select_option(label="Firma prueba UI (f_ui.png)")
        panel.locator("button:has-text('Firmar y aprobar')").click()
        expect(page.locator(".badge.grande.e-aprobada")).to_be_visible(timeout=15000)
        assert page.locator(".aprobar-panel").count() == 0
        print("2) firmada y aprobada desde la UI (badge Aprobada): OK")

        print("errores de consola:", len(errores))
        for e in errores: print("  -", e)
        nav.close()
finally:
    db2 = SessionLocal()
    db2.query(Evento).filter(Evento.factura_id == fid).delete()
    for dcc in db2.query(Documento).filter(Documento.factura_id == fid).all():
        db2.delete(dcc)
    fx = db2.get(Factura, fid)
    db2.delete(fx); db2.commit(); db2.close()
    almacen.eliminar("prueba_firma_ui/fv.pdf")
    almacen.eliminar("prueba_firma_ui/fv_firmado.pdf")
    c.delete(f"/api/firmas/{firma_id}")
    print("3) limpieza total: OK")
