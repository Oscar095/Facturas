"""Login, buscar un doc, hacer clic en 'Ver PDF' y volcar el HTML del modal
que queda abierto, para saber cómo cerrarlo."""
import sys, time
sys.path.insert(0, "backend")
from app.config import settings
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="es-CO", accept_downloads=True)
    page = ctx.new_page()
    page.goto(settings.url_facturas, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    page.locator("input[type='email'], input[type='text'], input[name*='user' i], "
                 "input[placeholder*='usuario' i], input[placeholder*='correo' i]").first.fill(settings.username_facturas)
    page.locator("input[type='password']").first.fill(settings.password_facturas)
    try:
        page.locator("button[type='submit']:visible").first.click(timeout=8000)
    except Exception:
        page.locator("input[type='password']").first.press("Enter")
    page.wait_for_url("**/documentRecepcion/**", timeout=45000)
    page.wait_for_load_state("networkidle", timeout=45000)
    time.sleep(2)

    print("¿Hay modal ANTES de buscar nada?", page.locator("[role='dialog']").count())

    page.locator("input[placeholder*='Desde' i]").first.fill("2026/07/15")
    page.locator("input[placeholder*='Hasta' i]").first.fill("2026/07/22")
    page.locator("button:has-text('Buscar')").first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(2)
    print("¿Hay modal después de la primera búsqueda?", page.locator("[role='dialog']").count())

    filas = page.locator("table tbody tr")
    print("filas encontradas:", filas.count())
    if filas.count() > 0:
        fila = filas.first
        fila.locator("button.btn-default-drop").click()
        time.sleep(0.5)
        print("¿Hay dropdown abierto? buscando 'Ver PDF'...")
        print("Ver PDF visible:", fila.locator("a:has-text('Ver PDF')").count())
        try:
            with page.expect_response(lambda r: "pdf-recepcion" in r.url, timeout=15000):
                fila.locator("a:has-text('Ver PDF')").click()
        except Exception as e:
            print("no se capturó response:", e)
        time.sleep(2)
        modal = page.locator("[role='dialog']")
        print("¿Hay modal DESPUÉS de Ver PDF?", modal.count())
        if modal.count() > 0:
            print("--- HTML del modal (primeros 3000 chars) ---")
            print(modal.first.evaluate("el => el.outerHTML").__getitem__(slice(0, 3000)))
    b.close()
