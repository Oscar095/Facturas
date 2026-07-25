"""UI: entrar a Mis Firmas, subir un PNG, ver la tarjeta con imagen, eliminarla."""
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea72d1e480000000049454e44ae426082")
tmp = Path(tempfile.mkdtemp()) / "firma_ui.png"
tmp.write_bytes(PNG)

errores = []
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

    # link visible en el sidebar y navegar
    link = page.locator(".sidenav a", has_text="Mis Firmas")
    expect(link).to_have_count(1)
    link.click()
    page.wait_for_selector("h1:has-text('Mis Firmas')", timeout=8000)
    print("1) página Mis Firmas abre desde el sidebar: OK")

    # subir
    page.set_input_files("input[type=file]", str(tmp))
    page.fill("input[placeholder*='Etiqueta']", "Firma UI")
    page.click("button:has-text('Subir firma')")
    tarjeta = page.locator(".firma-card", has_text="Firma UI")
    expect(tarjeta).to_have_count(1, timeout=8000)
    print("2) firma subida y tarjeta visible: OK")

    # la imagen carga (blob object URL)
    img = tarjeta.locator(".firma-imagen img")
    expect(img).to_be_visible(timeout=8000)
    src = img.get_attribute("src")
    print(f"3) vista previa cargada (src={src[:20]}…): OK")

    # eliminar
    tarjeta.locator("button:has-text('Eliminar')").click()
    expect(page.locator(".firma-card", has_text="Firma UI")).to_have_count(0, timeout=8000)
    expect(page.locator("p.ayuda", has_text="Aún no has subido")).to_have_count(1)
    print("4) firma eliminada, vuelve el estado vacío: OK")

    print("errores de consola:", len(errores))
    for e in errores:
        print("  -", e)
    b.close()
