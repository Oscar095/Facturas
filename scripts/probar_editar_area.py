"""Prueba el dropdown editable de área: asignar una factura sin área,
y cambiar la de una que ya tenía área asignada."""
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
    page.on("console", lambda m: print("CONSOLE", m.type, m.text) if m.type == "error" else None)

    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.fill("input[type=email]", "oscar.orozco03@gmail.com")
    page.fill("input[type=password]", "Admin1234*")
    page.click("button:has-text('Ingresar')")
    page.wait_for_url("**/facturas", timeout=15000)
    page.wait_for_selector("table.tabla tbody tr td.mono", timeout=8000)

    # 1) Factura "sin asignar" -> asignarle un área
    fila_sin = page.locator("table.tabla tbody tr", has=page.locator("td:has-text('sin asignar')")).first
    folio = fila_sin.locator("td.mono").first.inner_text()
    fila_sin.click()
    page.wait_for_selector(".select-area", timeout=8000)
    print(f"[{folio}] antes:", page.locator(".select-area").input_value() or "(vacío)")
    page.select_option(".select-area", label="MANTENIMIENTO")
    page.wait_for_function(
        "document.querySelector('.select-area').value !== ''", timeout=8000
    )
    time.sleep(0.5)
    print(f"[{folio}] después de asignar:", page.locator(".select-area").input_value())
    page.screenshot(path=str(SALIDA / "01_area_asignada.png"))

    # 2) Volver y cambiar una factura que YA tenía área a otra distinta
    page.go_back(wait_until="networkidle")
    page.wait_for_selector("table.tabla tbody tr td.mono", timeout=8000)
    fila_con = page.locator(
        "table.tabla tbody tr",
        has=page.locator("td:has-text('PRODUCCION')"),
    ).first
    folio2 = fila_con.locator("td.mono").first.inner_text()
    fila_con.click()
    page.wait_for_selector(".select-area", timeout=8000)
    antes = page.locator(".select-area").input_value()
    page.select_option(".select-area", label="CALIDAD")
    time.sleep(1)
    despues = page.locator(".select-area").input_value()
    print(f"[{folio2}] cambiado de área_id={antes} a área_id={despues}")
    page.screenshot(path=str(SALIDA / "02_area_cambiada.png"))

    b.close()
print("OK")
