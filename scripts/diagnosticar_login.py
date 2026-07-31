"""Diagnóstico: reproduce el login paso a paso y captura URL, texto visible y
pantallazo de lo que muestra el portal tras enviar credenciales."""
import sys
import time
from pathlib import Path

sys.path.insert(0, "backend")
from playwright.sync_api import sync_playwright
from app.config import settings

SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("descargas/diag")
SALIDA.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(locale="es-CO").new_page()
    respuestas = []
    page.on("response", lambda r: respuestas.append((r.status, r.url[:110]))
            if "siesa" in r.url and r.status >= 400 else None)

    page.goto(settings.url_facturas, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    print(f"1) página de login cargada: {page.url}")
    page.screenshot(path=str(SALIDA / "1_login.png"))

    page.locator(
        "input[type='email'], input[type='text'], input[name*='user' i], "
        "input[placeholder*='usuario' i], input[placeholder*='correo' i]"
    ).first.fill(settings.username_facturas)
    page.locator("input[type='password']").first.fill(settings.password_facturas)
    try:
        page.locator("button[type='submit']:visible").first.click(timeout=8000)
    except Exception:
        page.locator("input[type='password']").first.press("Enter")
    print("2) credenciales enviadas, esperando 15s a ver qué pasa…")
    time.sleep(15)

    print(f"3) URL actual: {page.url}")
    page.screenshot(path=str(SALIDA / "2_despues_login.png"), full_page=True)

    # texto visible (para leer mensajes de error del portal)
    texto = page.evaluate("() => document.body.innerText")
    lineas = [l.strip() for l in texto.splitlines() if l.strip()][:40]
    print("4) texto visible en la página:")
    for l in lineas:
        print("   |", l)

    # ¿modales abiertos?
    modales = page.locator(".modal.in, .modal.show, [uib-modal-window]").count()
    print(f"5) modales abiertos: {modales}")
    if modales:
        for m in page.locator(".modal.in, .modal.show, [uib-modal-window]").all()[:3]:
            try:
                print("   modal:", m.inner_text()[:400].replace("\n", " | "))
            except Exception:
                pass

    if respuestas:
        print("6) respuestas HTTP con error:")
        for st, u in respuestas[:10]:
            print(f"   {st} {u}")
    b.close()
