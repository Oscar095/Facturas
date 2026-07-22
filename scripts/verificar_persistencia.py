import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SALIDA = Path(sys.argv[1])
BASE = "http://127.0.0.1:8000"

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 900})
    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.fill("input[type=email]", "oscar.orozco03@gmail.com")
    page.fill("input[type=password]", "Admin1234*")
    page.click("button:has-text('Ingresar')")
    page.wait_for_url("**/facturas", timeout=15000)
    page.wait_for_selector("table.tabla tbody tr td.mono", timeout=8000)

    fila = page.locator("table.tabla tbody tr", has=page.locator("td.mono:has-text('32008358')")).first
    fila.click()
    page.wait_for_selector(".select-area", timeout=8000)
    time.sleep(0.5)
    valor = page.locator(".select-area").input_value()
    texto_opcion = page.locator(".select-area option:checked").inner_text()
    print(f"Tras recargar la página: select-area value={valor} texto='{texto_opcion}'")
    page.screenshot(path=str(SALIDA / "persistencia.png"))
    b.close()
