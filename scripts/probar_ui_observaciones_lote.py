"""UI de los cambios sobre facturas SINTÉTICAS de un proveedor de prueba
(nunca toca facturas reales):

  1. Historial de observaciones al final del detalle: se agregan varias, se
     acumulan con autor y fecha, y no hay forma de editar las anteriores.
  2. Los filtros sobreviven al ir al detalle y volver (viven en la URL).
  3. La casilla de selección solo se activa en facturas PROCESADAS.
  4. Aprobar y firmar en bloque desde la tabla.
  5. La columna de valor muestra el subtotal (sin IVA), y marca con * las
     facturas cuyo IVA no se pudo determinar.

Crea proveedor, facturas, documentos, blobs y firma propios y los borra al final.
Uso: .venv/Scripts/python.exe scripts/probar_ui_observaciones_lote.py
"""
import sys

sys.path.insert(0, "backend")
from decimal import Decimal  # noqa: E402
from io import BytesIO  # noqa: E402

import httpx  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Area, Documento, Evento, Factura, Observacion, Proveedor, ahora,
)
from app.services.blob_storage import get_almacen  # noqa: E402

BASE = "http://127.0.0.1:8000"
NIT = "900000000-1"  # proveedor sintético: aísla el listado de las facturas reales
NOTA1 = "Falta el CRN: el proveedor despacha el lunes."
NOTA2 = "Compras confirma que la OCS cubre todo el servicio."
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


# (numero, estado, con_area, valor_total, iva)
CASOS = [
    ("UILOTE-1", "procesada", True, Decimal("1190000.00"), Decimal("190000.00")),
    ("UILOTE-2", "procesada", True, Decimal("500000.00"), Decimal("0.00")),
    # aún no procesada -> su casilla debe quedar deshabilitada
    ("UILOTE-3", "lista_contabilizar", True, Decimal("700000.00"), None),
]

db = SessionLocal()
area = db.execute(select(Area)).scalars().first()
prov = db.execute(select(Proveedor).where(Proveedor.nit == NIT)).scalar_one_or_none()
if prov is None:
    prov = Proveedor(nit=NIT, razon_social="PROVEEDOR PRUEBA UI")
    db.add(prov); db.flush()
prov_id = prov.id
ids = {}
for numero, estado, con_area, total, iva in CASOS:
    ruta = f"prueba_ui_lote/{numero}.pdf"
    almacen.subir(ruta, pdf_prueba(), content_type="application/pdf")
    f = Factura(cufe=f"TESTUI-{numero}", prefijo="", numero=numero, proveedor_id=prov_id,
                fecha_emision=ahora(), fecha_recepcion=ahora(), estado_proceso=estado,
                valor_total=total, iva=iva,
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
        page = b.new_context(viewport={"width": 1500, "height": 1000}).new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(str(e)))
        page.on("dialog", lambda d: d.accept())

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
        print("1) filtro por proveedor sintético: 3 filas y la URL lo refleja: OK")

        # ── 2) la columna muestra el SUBTOTAL, no el total ──
        expect(page.locator("table.tabla thead th", has_text="Valor sin IVA")).to_have_count(1)
        fila1 = page.locator("table.tabla tbody tr", has_text="UILOTE-1")
        texto_valor = fila1.locator("td.der").inner_text()
        assert "1.000.000" in texto_valor, f"debería mostrar el subtotal: {texto_valor!r}"
        assert "1.190.000" not in texto_valor, f"está mostrando el total con IVA: {texto_valor!r}"
        print(f"2) UILOTE-1 (total 1.190.000, IVA 190.000) se muestra como {texto_valor.strip()!r}: OK")

        fila3 = page.locator("table.tabla tbody tr", has_text="UILOTE-3")
        assert fila3.locator(".iva-desconocido").count() == 1, \
            "la factura sin IVA determinado debe marcarse con *"
        assert fila1.locator(".iva-desconocido").count() == 0
        print("3) la factura con IVA indeterminado se marca con * y las demás no: OK")

        # ── 4) historial de observaciones al final del detalle ──
        fila1.click()
        page.wait_for_selector("h1:has-text('UILOTE-1')", timeout=8000)
        expect(page.locator("h2:has-text('Observaciones')")).to_have_count(1)
        expect(page.locator(".obs-vacio")).to_have_count(1)
        page.fill(".observaciones textarea", NOTA1)
        page.click("button:has-text('Agregar observación')")
        expect(page.locator(".obs-historial li")).to_have_count(1, timeout=8000)
        assert page.input_value(".observaciones textarea") == "", "el campo debe quedar limpio"
        page.fill(".observaciones textarea", NOTA2)
        page.click("button:has-text('Agregar observación')")
        expect(page.locator(".obs-historial li")).to_have_count(2, timeout=8000)
        textos = page.locator(".obs-texto").all_inner_texts()
        assert textos == [NOTA1, NOTA2], textos
        assert page.locator(".obs-meta b").first.inner_text().strip() != ""
        print("4) historial: 2 notas acumuladas en orden, con autor, y el campo se limpia: OK")

        # el detalle no ofrece forma de editar o borrar una nota ya escrita
        assert page.locator(".obs-historial button").count() == 0
        assert page.locator(".obs-historial textarea").count() == 0
        print("5) las notas ya escritas no se pueden editar ni borrar: OK")

        # el valor del detalle también es el subtotal
        assert "1.000.000" in page.locator(".detalle-datos").inner_text()
        print("6) el detalle muestra el valor sin IVA: OK")

        # ── 7) volver conserva el filtro ──
        page.click("button.volver")
        page.wait_for_selector("table.tabla tbody tr", timeout=8000)
        assert page.input_value(".filtros input[placeholder*='proveedor']") == NIT, \
            "el filtro se perdió al volver"
        expect(page.locator("table.tabla tbody tr")).to_have_count(3, timeout=8000)
        print("7) al volver del detalle el filtro sigue puesto: OK")

        marca = page.locator("table.tabla tbody tr", has_text="UILOTE-1").locator(".marca-obs")
        expect(marca).to_have_count(1)
        assert NOTA1 in marca.get_attribute("title") and NOTA2 in marca.get_attribute("title")
        print("8) la fila muestra el indicador con las 2 notas en el tooltip: OK")

        # ── 9) la casilla solo se activa en PROCESADAS ──
        casilla3 = page.locator("table.tabla tbody tr", has_text="UILOTE-3").locator(
            "td.col-check input")
        assert casilla3.is_disabled(), \
            "una factura que no está procesada no debería poder seleccionarse"
        page.locator("thead th.col-check input").check()
        expect(page.locator(".barra-lote")).to_contain_text("2 factura(s)", timeout=5000)
        assert page.locator("table.tabla tbody tr.marcada").count() == 2
        print("9) 'seleccionar todas' marca solo las 2 procesadas: OK")

        page.locator("table.tabla tbody tr", has_text="UILOTE-1").locator(
            "td.col-check input").uncheck()
        assert "/facturas/" not in page.url, f"la casilla abrió el detalle: {page.url}"
        page.locator("thead th.col-check input").check()
        print("10) marcar/desmarcar no abre el detalle: OK")

        # ── 11) aprobar y firmar en bloque ──
        page.click(".barra-lote button:has-text('Aprobar y firmar')")
        page.wait_for_selector(".barra-lote select", timeout=8000)
        page.click(".barra-lote button:has-text('Confirmar y firmar')")
        expect(page.locator(".aviso")).to_contain_text("2 factura(s) aprobadas", timeout=60000)
        expect(page.locator("table.tabla tbody tr", has_text="UILOTE-1")
               .locator(".badge.e-aprobada")).to_have_count(1, timeout=8000)
        expect(page.locator(".barra-lote")).to_have_count(0)
        print("11) aprobación en bloque: 2 aprobadas y la tabla se recarga: OK")

        db2 = SessionLocal()
        f1 = db2.get(Factura, ids["UILOTE-1"])
        f3 = db2.get(Factura, ids["UILOTE-3"])
        assert f1.estado_proceso == "aprobada" and f1.blob_pdf.endswith("_firmado.pdf")
        assert len(f1.observaciones) == 2
        assert f3.estado_proceso == "lista_contabilizar", "la no procesada no debió tocarse"
        db2.close()
        print("12) BD: firmadas, con su historial; la no procesada intacta: OK")

        print("errores de consola:", len(errores))
        for e in errores:
            print("  -", e)
        b.close()
finally:
    db3 = SessionLocal()
    for fid in ids.values():
        db3.query(Evento).filter(Evento.factura_id == fid).delete()
        db3.query(Observacion).filter(Observacion.factura_id == fid).delete()
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
    for numero, *_ in CASOS:
        for ruta in (f"prueba_ui_lote/{numero}.pdf", f"prueba_ui_lote/{numero}_firmado.pdf"):
            try:
                almacen.eliminar(ruta)
            except Exception:  # noqa: BLE001 — el firmado no existe si no se aprobó
                pass
    cli.delete(f"/api/firmas/{firma_id}")
    print("limpieza (proveedor, facturas, documentos, eventos, blobs y firma): OK")
