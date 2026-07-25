"""UI: en una factura sintética, ver botón Procesar -> clic -> badge Procesada y
botón Aprobar -> clic -> badge Aprobada y botón contabilizar (admin). Limpia al final."""
import sys
sys.path.insert(0, "backend")
from sqlalchemy import select
from playwright.sync_api import sync_playwright, expect
from app.database import SessionLocal
from app.models import Area, Evento, Factura, Proveedor, ahora

db = SessionLocal()
prov = db.execute(select(Proveedor)).scalars().first()
area = db.execute(select(Area)).scalars().first()
f = Factura(cufe="TEST-UI-APROBACION", prefijo="", numero="TEST-UI-1", proveedor_id=prov.id,
            fecha_recepcion=ahora(), estado_proceso="asignada", area_id=area.id)
db.add(f); db.commit()
fid = f.id
print(f"factura sintética id={fid}")

errores = []
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errores.append(str(e)))
        page.on("dialog", lambda d: d.accept())

        page.goto("http://127.0.0.1:8000/login", wait_until="networkidle")
        page.fill("input[type=email]", "oscar.orozco03@gmail.com")
        page.fill("input[type=password]", "Admin1234*")
        page.click("button:has-text('Ingresar')")
        page.wait_for_selector(".sidebar", timeout=15000)

        page.goto(f"http://127.0.0.1:8000/facturas/{fid}", wait_until="networkidle")
        page.wait_for_selector("h1:has-text('TEST-UI-1')", timeout=8000)

        # estado inicial: aviso de faltantes + botón Procesar, sin Aprobar
        expect(page.locator(".aviso")).to_be_visible()
        btn_procesar = page.locator("button:has-text('Procesar')")
        expect(btn_procesar).to_have_count(1)
        assert page.locator("button:has-text('Aprobar factura')").count() == 0
        print("1) asignada: aviso de faltantes + botón Procesar (sin Aprobar): OK")

        btn_procesar.click()  # el confirm se acepta solo (dialog handler)
        expect(page.locator(".badge.grande.e-procesada")).to_be_visible(timeout=8000)
        expect(page.locator("button:has-text('Aprobar factura')")).to_have_count(1)
        assert page.locator("button:has-text('Procesar')").count() == 0
        assert page.locator(".aviso").count() == 0  # el aviso de faltantes desaparece
        print("2) procesada: badge + botón Aprobar aparece, Procesar y aviso desaparecen: OK")

        page.locator("button:has-text('Aprobar factura')").click()
        expect(page.locator(".badge.grande.e-aprobada")).to_be_visible(timeout=8000)
        expect(page.locator("button:has-text('Marcar como contabilizada')")).to_have_count(1)
        assert page.locator("button:has-text('Aprobar factura')").count() == 0
        print("3) aprobada: badge + botón contabilizar (admin): OK")

        print("errores de consola:", len(errores))
        for e in errores: print("  -", e)
        b.close()
finally:
    db2 = SessionLocal()
    db2.query(Evento).filter(Evento.factura_id == fid).delete()
    fx = db2.get(Factura, fid)
    db2.delete(fx); db2.commit(); db2.close()
    print("4) limpieza: OK")
