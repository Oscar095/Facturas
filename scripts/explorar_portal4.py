"""Descubrimiento paso 4: capturar los BYTES del PDF interceptando la respuesta
de red (application/pdf) al hacer clic en "Ver PDF" de una fila filtrada por CUFE.

Si esto funciona, la estrategia de ingesta es:
  listado por HTTP (metadatos + cufe) -> por cada CUFE nuevo, filtrar en la UI,
  clic en Ver PDF, capturar response.body() -> subir a Blob.

Uso:
    python scripts/explorar_portal4.py <carpeta_salida> <cufe>
"""
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
URL = os.environ["URL_FACTURAS"].strip()
USUARIO = os.environ["USERNAME_FACTURAS"].strip()
CLAVE = os.environ["PASSWORD_FACTURAS"].strip()

SALIDA = Path(sys.argv[1])
CUFE = sys.argv[2]
SALIDA.mkdir(parents=True, exist_ok=True)

pdf_bytes = {"data": None, "url": None}
vistos = []


def capturar_pdf(res):
    ct = res.headers.get("content-type", "")
    if "pdf-recepcion" in res.url or "application/pdf" in ct:
        vistos.append({"url": res.url, "ct": ct, "status": res.status})
        try:
            body = res.body()
            if body and body[:4] == b"%PDF":
                pdf_bytes["data"] = body
                pdf_bytes["url"] = res.url
                print(f"  capturado {len(body)} bytes de {res.url}")
        except Exception as e:
            print(f"  no se pudo leer body de {res.url}: {e}")


def login(page):
    page.goto(URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    page.locator(
        "input[type='email'], input[type='text'], input[name*='user' i], "
        "input[placeholder*='usuario' i], input[placeholder*='correo' i]"
    ).first.fill(USUARIO)
    page.locator("input[type='password']").first.fill(CLAVE)
    try:
        page.locator("button[type='submit']:visible").first.click(timeout=8000)
    except Exception:
        page.locator("input[type='password']").first.press("Enter")
    page.wait_for_url("**/documentRecepcion/**", timeout=45000)
    page.wait_for_load_state("networkidle", timeout=45000)
    time.sleep(3)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale="es-CO", accept_downloads=True)
    page = context.new_page()
    context.on("response", capturar_pdf)

    print("Login...")
    login(page)

    print(f"Filtrando por CUFE {CUFE[:20]}...")
    page.locator("input[placeholder*='CUFE' i]").first.fill(CUFE)
    page.locator("button:has-text('Buscar')").first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(3)

    n = page.locator("table tbody tr").count()
    print(f"Filas: {n}")
    if n == 0:
        print("Sin resultados para ese CUFE")
        browser.close()
        sys.exit(1)

    fila = page.locator("table tbody tr").first
    fila.locator("button.btn-default-drop").click()
    time.sleep(1)
    # Abrir Ver PDF (nueva pestaña) — la respuesta application/pdf la capturamos por el handler
    nueva = None
    try:
        with context.expect_page(timeout=15000) as info:
            fila.locator("a:has-text('Ver PDF')").click()
        nueva = info.value
    except Exception as e:
        print(f"click Ver PDF: {e}")
    # esperar hasta 20s a que llegue el PDF
    for _ in range(20):
        if pdf_bytes["data"]:
            break
        time.sleep(1)
    print(f"Respuestas PDF vistas: {vistos}")

    if pdf_bytes["data"]:
        destino = SALIDA / f"captura_{CUFE[:12]}.pdf"
        destino.write_bytes(pdf_bytes["data"])
        print(f"PDF capturado: {len(pdf_bytes['data'])} bytes -> {destino}")
        print(f"URL PDF: {pdf_bytes['url']}")
    else:
        print("NO se capturó PDF")
    browser.close()
