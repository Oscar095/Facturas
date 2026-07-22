"""Prueba real: abrir el detalle de una factura y hacer clic para ver el PDF,
capturando errores de red/consola (para confirmar que ya no falla por CORS)."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SALIDA = Path(sys.argv[1])
SALIDA.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"

errores = []
paginas_nuevas = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    context = b.new_context()
    page = context.new_page()
    page.on("console", lambda m: errores.append(f"CONSOLE {m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errores.append(f"PAGEERROR: {e}"))
    page.on("requestfailed", lambda r: errores.append(f"REQUESTFAILED: {r.url} -> {r.failure}"))
    context.on("page", lambda p2: paginas_nuevas.append(p2))

    page.goto(BASE, wait_until="networkidle", timeout=30000)
    page.fill("input[type=email]", "oscar.orozco03@gmail.com")
    page.fill("input[type=password]", "Admin1234*")
    page.click("button:has-text('Ingresar')")
    page.wait_for_url("**/facturas", timeout=15000)
    page.wait_for_selector("table.tabla tbody tr td.mono", timeout=8000)

    page.locator("table.tabla tbody tr").first.click()
    page.wait_for_selector("table.tabla tbody tr", timeout=8000)  # tabla de documentos
    time.sleep(1)

    # clic en el nombre del archivo FV (primer link de la tabla de documentos del detalle)
    with context.expect_page(timeout=10000) as info:
        page.locator("table.tabla tbody tr td a").first.click()
    nueva = info.value
    time.sleep(2)  # el visor de PDF nativo de Chrome no siempre dispara 'load'
    print("URL de la pestaña nueva:", nueva.url)

    # Confirmar en la página ORIGINAL que no se disparó el error del catch()
    hay_error_ui = page.locator(".error").count() > 0
    print("¿La UI muestra mensaje de error?", hay_error_ui)

    print(f"\nErrores capturados: {len(errores)}")
    for e in errores:
        print(" -", e)

    b.close()
