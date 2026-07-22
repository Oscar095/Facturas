"""Prueba end-to-end de la UI servida por el backend (puerto 8000) con Playwright."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SALIDA = Path(sys.argv[1])
SALIDA.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 900})
    page.on("console", lambda m: print("CONSOLE", m.type, m.text))
    page.on("pageerror", lambda e: print("PAGEERROR", e))

    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.screenshot(path=str(SALIDA / "01_login.png"))

    page.fill("input[type=email]", "oscar.orozco03@gmail.com")
    page.fill("input[type=password]", "Admin1234*")
    page.click("button:has-text('Ingresar')")
    page.wait_for_url("**/facturas", timeout=15000)
    page.wait_for_load_state("networkidle")
    # esperar a que aparezca una fila de datos o el mensaje de vacío
    try:
        page.wait_for_selector("table.tabla tbody tr td.mono", timeout=8000)
    except Exception:
        print("No aparecieron filas de datos")
    time.sleep(1)
    page.screenshot(path=str(SALIDA / "02_facturas.png"), full_page=True)
    print("Facturas visibles:", page.locator("table.tabla tbody tr").count())

    # abrir la primera factura
    page.locator("table.tabla tbody tr").first.click()
    page.wait_for_url("**/facturas/*", timeout=15000)
    page.wait_for_selector(".detalle-datos", timeout=10000)
    page.wait_for_selector("table.tabla tbody tr td .badge.tipo", timeout=8000)
    time.sleep(0.5)
    page.screenshot(path=str(SALIDA / "03_detalle.png"), full_page=True)
    print("Documentos en detalle:", page.locator("table.tabla tbody tr").count())

    # ir a administración -> áreas y reglas
    page.goto(f"{BASE}/admin", wait_until="networkidle")
    page.wait_for_selector(".tabs", timeout=8000)
    page.click("text=Áreas y reglas")
    page.wait_for_selector("table.tabla tbody tr", timeout=8000)
    time.sleep(0.5)
    page.screenshot(path=str(SALIDA / "06_admin_reglas.png"), full_page=True)
    print("Filas de reglas visibles:", page.locator("table.tabla tbody tr").count())

    b.close()
print("Screenshots en", SALIDA)
