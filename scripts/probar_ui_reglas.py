"""UI: crear una regla desde el admin, editarla y eliminarla, con esperas explícitas."""
from playwright.sync_api import sync_playwright, expect

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
    page.wait_for_selector(".sidebar, .app-shell", timeout=15000)

    page.goto("http://127.0.0.1:8000/admin", wait_until="networkidle")
    page.click("button.tab:has-text('Áreas y reglas')")
    page.wait_for_selector("h3:has-text('Nueva regla')", timeout=8000)

    # crear
    page.fill("input[placeholder='Proveedor']", "UI PRUEBA SAS")
    page.fill("input[placeholder='NIT']", "911222333")
    page.fill("input[placeholder='Patrón de ítem (opcional)']", "cinta transportadora")
    page.select_option("form.form-linea:has(input[placeholder='Proveedor']) select", index=1)
    page.click("button:has-text('Crear regla')")
    page.fill("input.buscador", "UI PRUEBA")
    fila = page.locator("table.tabla tbody tr", has_text="UI PRUEBA SAS")
    expect(fila).to_have_count(1, timeout=8000)
    print("1) regla creada y visible: OK")

    # editar
    fila.locator("button:has-text('Editar')").click()
    page.locator("tr.fila-edicion input").nth(2).fill("banda transportadora")
    page.locator("button:has-text('Guardar')").click()
    expect(page.locator("table.tabla tbody tr", has_text="banda transportadora")).to_have_count(1, timeout=8000)
    err = page.locator(".error")
    print("2) patrón editado visible: OK", "| error UI:", err.inner_text() if err.count() else "ninguno")

    # eliminar
    fila = page.locator("table.tabla tbody tr", has_text="UI PRUEBA SAS")
    fila.locator("button:has-text('Eliminar')").click()
    expect(page.locator("table.tabla tbody tr", has_text="UI PRUEBA SAS")).to_have_count(0, timeout=8000)
    print("3) regla eliminada: OK")

    print("errores de consola:", len(errores))
    b.close()
