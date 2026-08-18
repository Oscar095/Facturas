"""UI de los tres cambios, sobre facturas SINTÉTICAS de un proveedor de prueba
(nunca toca facturas reales):

  1. Observaciones en el detalle: se escriben, se guardan y quedan visibles;
     en el listado aparece el indicador 💬 con la nota en el tooltip.
  2. Los filtros sobreviven al ir al detalle y volver (viven en la URL).
  3. Selección múltiple + "Aprobar y firmar" en bloque desde la tabla.

Crea proveedor, facturas, documentos, blobs y firma propios y los borra al final.
Uso: .venv/Scripts/python.exe scripts/probar_ui_observaciones_lote.py
"""
import sys

sys.path.insert(0, "backend")
from io import BytesIO  # noqa: E402

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Area, Documento, Evento, Factura, Proveedor, ahora  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402

BASE = "http://127.0.0.1:8000"
NIT = "900000000-1"  # proveedor sintético: aísla el listado de las facturas reales
NOTA = "Falta el CRN: el proveedor despacha el lunes. Aprobar de todas formas."
almacen = get_almacen()

img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
ImageDraw.Draw(img).line([(20, 100), (120, 40), (240, 110), (340, 60)],
                         fill=(25, 35, 95, 255), width=6)
_b = BytesIO(); img.save(_b, "PNG"); PNG_FIRMA = _b.getvalue()


def pdf_prueba():
    b = BytesIO()
    c = rl_canvas.Canvas(b, pagesize=(612, 792))
    c.drawString(72, 720, "FACTURA DE PRUEBA UI")
    c.showPage(); c.save()
    return b.getvalue()


CASOS = [
    ("UILOTE-1", "lista_contabilizar", True),
    ("UILOTE-2", "procesada", True),
    ("UILOTE-3", "nueva", False),  # sin área: su casilla debe quedar deshabilitada
]

db = SessionLocal()
area = db.execute(select(Area)).scalars().first()
prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
if prov is None:
    prov = Proveedor(nit=NIT, razon_social="PROVEEDOR PRUEBA UI")
    db.add(prov); db.flush()
prov_id = prov.id
ids = {}
for numero, estado, con_area in CASOS:
    ruta = f"prueba_ui_lote/{numero}.pdf"
    almacen.subir(ruta, pdf_prueba(), content_type="application/pdf")
    f = Factura(cufe=f"TESTUI-{numero}", prefijo="", numero=numero, proveedor_id=prov_id,
                fecha_recepcion=ahora(), estado_proceso=estado,
                area_id=area.id if con_area else None, blob_pdf=ruta)
    db.add(f); db.flush()
    db.add(Documento(factura_id=f.id, tipo="FV", blob_path=ruta, nombre_archivo=f"{numero}.pdf"))
    ids[numero] = f.id
db.commit(); db.close()
print(f"facturas sintéticas: {ids}")

cli = httpx.Client(base_url=BASE, timeout=60)
tok = cli.post("/api/auth/login",
               data={"username": "oscar.orozco03@gmail.com",
                     "password": "Admin1234*"}).json()["access_token"]
cli.headers["Authorization"] = f"Bearer {tok}"
firma_id = cli.post("/api/firmas", files={"archivo": ("firma_ui.png", PNG_FIRMA, "image/png")},
                    data={"nombre": "Firma prueba UI lote"}).json()["id"]

errores = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(str(e)))
        page.on("dialog", lambda d: d.accept())  # los confirm() del flujo

        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.fill("input[type=email]", "oscar.orozco03@gmail.com")
        page.fill("input[type=password]", "Admin1234*")
        page.click("button:has-text('Ingresar')")
        page.wait_for_selector(".sidebar", timeout=15000)

        # ── 1) filtrar por el proveedor sintético ──
        page.goto(f"{BASE}/facturas", wait_until="networkidle")
        page.fill(".filtros input[placeholder*='proveedor']", NIT)
        expect(page.locator("table.tabla tbody tr")).to_have_count(3, timeout=8000)
        assert "proveedor=" in page.url, f"el filtro no quedó en la URL: {page.url}"
        print(f"1) filtro por proveedor sintético: 3 filas y la URL lo refleja ({page.url}): OK")

        # ── 2) observaciones en el detalle ──
        page.locator("table.tabla tbody tr", has_text="UILOTE-1").click()
        page.wait_for_selector("h1:has-text('UILOTE-1')", timeout=8000)
        expect(page.locator(".observaciones textarea")).to_have_count(1)
        page.fill(".observaciones textarea", NOTA)
        expect(page.locator(".sin-guardar")).to_have_count(1)
        page.click("button:has-text('Guardar observaciones')")
        expect(page.locator(".sin-guardar")).to_have_count(0, timeout=8000)
        assert page.locator(".error").count() == 0
        print("2) observaciones: se escriben, avisan 'sin guardar' y se guardan: OK")

        # ── 3) volver conserva el filtro (el punto del cambio) ──
        page.click("button.volver")
        page.wait_for_selector("table.tabla tbody tr", timeout=8000)
        valor = page.input_value(".filtros input[placeholder*='proveedor']")
        assert valor == NIT, f"el filtro se perdió al volver: {valor!r}"
        expect(page.locator("table.tabla tbody tr")).to_have_count(3, timeout=8000)
        print("3) al volver del detalle el filtro sigue puesto y la tabla filtrada: OK")

        # el indicador de observaciones viaja en el listado
        fila1 = page.locator("table.tabla tbody tr", has_text="UILOTE-1")
        expect(fila1.locator(".marca-obs")).to_have_count(1)
        assert fila1.locator(".marca-obs").get_attribute("title") == NOTA
        print("4) la fila muestra el indicador de nota con el texto en el tooltip: OK")

        # ── 5) selección múltiple ──
        casilla3 = page.locator("table.tabla tbody tr", has_text="UILOTE-3").locator(
            "td.col-check input")
        assert casilla3.is_disabled(), "una factura sin área no debería poder seleccionarse"
        page.locator("thead th.col-check input").check()
        expect(page.locator(".barra-lote")).to_contain_text("2 factura(s)", timeout=5000)
        assert page.locator("table.tabla tbody tr.marcada").count() == 2
        print("5) 'seleccionar todas' marca solo las 2 aprobables (la sin área queda fuera): OK")

        # el clic en la casilla no debe abrir el detalle
        page.locator("table.tabla tbody tr", has_text="UILOTE-1").locator(
            "td.col-check input").uncheck()
        assert "/facturas/" not in page.url, f"la casilla abrió el detalle: {page.url}"
        expect(page.locator(".barra-lote")).to_contain_text("1 factura(s)")
        page.locator("thead th.col-check input").check()
        print("6) marcar/desmarcar no abre el detalle: OK")

        # ── 7) aprobar y firmar en bloque ──
        page.click(".barra-lote button:has-text('Aprobar y firmar')")
        page.wait_for_selector(".barra-lote select", timeout=8000)
        page.click(".barra-lote button:has-text('Confirmar y firmar')")
        expect(page.locator(".aviso")).to_contain_text("2 factura(s) aprobadas", timeout=60000)
        print("7) aprobación en bloque: aviso de 2 aprobadas: OK")

        expect(page.locator("table.tabla tbody tr", has_text="UILOTE-1")
               .locator(".badge.e-aprobada")).to_have_count(1, timeout=8000)
        expect(page.locator("table.tabla tbody tr", has_text="UILOTE-2")
               .locator(".badge.e-aprobada")).to_have_count(1)
        expect(page.locator(".barra-lote")).to_have_count(0)
        print("8) la tabla se recarga con las 2 en estado Aprobada y sin selección: OK")

        db2 = SessionLocal()
        f1 = db2.get(Factura, ids["UILOTE-1"])
        f3 = db2.get(Factura, ids["UILOTE-3"])
        assert f1.estado_proceso == "aprobada" and f1.observaciones == NOTA
        assert f1.blob_pdf.endswith("_firmado.pdf"), f1.blob_pdf
        assert f3.estado_proceso == "nueva", "la factura sin área no debió tocarse"
        db2.close()
        print("9) BD: firmadas y con la observación; la sin área intacta: OK")

        print("errores de consola:", len(errores))
        for e in errores:
            print("  -", e)
        b.close()
finally:
    db3 = SessionLocal()
    for fid in ids.values():
        db3.query(Evento).filter(Evento.factura_id == fid).delete()
        for d in db3.query(Documento).filter(Documento.factura_id == fid).all():
            db3.delete(d)
        obj = db3.get(Factura, fid)
        if obj:
            db3.delete(obj)
    db3.flush()
    prov_obj = db3.get(Proveedor, prov_id)
    if prov_obj:
        db3.delete(prov_obj)
    db3.commit(); db3.close()
    for numero, _, _ in CASOS:
        for ruta in (f"prueba_ui_lote/{numero}.pdf", f"prueba_ui_lote/{numero}_firmado.pdf"):
            try:
                almacen.eliminar(ruta)
            except Exception:  # noqa: BLE001 — el firmado no existe si no se aprobó
                pass
    cli.delete(f"/api/firmas/{firma_id}")
    print("limpieza (proveedor, facturas, documentos, eventos, blobs y firma): OK")
