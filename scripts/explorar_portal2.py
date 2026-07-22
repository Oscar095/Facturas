"""Descubrimiento paso 2: buscar documentos por rango de fechas y capturar
el endpoint del listado, los botones de acción por fila y el mecanismo de descarga.

Uso:
    python scripts/explorar_portal2.py [carpeta_salida] [fecha_desde] [fecha_hasta]
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

URL = os.environ["URL_FACTURAS"].strip()
USUARIO = os.environ["USERNAME_FACTURAS"].strip()
CLAVE = os.environ["PASSWORD_FACTURAS"].strip()

SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("descargas/exploracion2")
FECHA_DESDE = sys.argv[2] if len(sys.argv) > 2 else "2026/07/01"
FECHA_HASTA = sys.argv[3] if len(sys.argv) > 3 else "2026/07/17"
SALIDA.mkdir(parents=True, exist_ok=True)

llamadas = []


def registrar_respuesta(res):
    req = res.request
    if "PortalPTBack" not in res.url:
        return
    item = {
        "metodo": req.method,
        "url": res.url,
        "status": res.status,
        "content_type": res.headers.get("content-type", ""),
        "req_headers": {
            k: v for k, v in req.headers.items()
            if k.lower() in ("authorization", "token", "x-csrf-token", "cookie", "content-type")
        },
    }
    if req.post_data:
        item["request_body"] = req.post_data[:3000]
    try:
        item["respuesta"] = res.text()[:6000]
    except Exception:
        item["respuesta"] = "<binario o no disponible>"
    llamadas.append(item)


def login(page):
    page.goto(URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    page.locator(
        "input[type='email'], input[type='text'], input[name*='user' i], "
        "input[placeholder*='usuario' i], input[placeholder*='correo' i]"
    ).first.fill(USUARIO)
    page.locator("input[type='password']").first.fill(CLAVE)
    page.locator(
        "button[type='submit'], button:has-text('Ingresar'), button:has-text('Iniciar'), "
        "button:has-text('Entrar'), button:has-text('Login')"
    ).first.click()
    page.wait_for_url("**/documentRecepcion/**", timeout=45000)
    page.wait_for_load_state("networkidle", timeout=45000)
    time.sleep(3)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale="es-CO", accept_downloads=True)
    page = context.new_page()
    page.on("response", registrar_respuesta)

    print("Iniciando sesión...")
    login(page)

    # Tokens en storage
    storage = page.evaluate(
        """() => ({local: {...localStorage}, session: {...sessionStorage},
                   cookies: document.cookie})"""
    )
    (SALIDA / "storage.json").write_text(
        json.dumps(storage, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Llenar fechas y buscar
    print(f"Buscando documentos entre {FECHA_DESDE} y {FECHA_HASTA} ...")
    desde = page.locator("input[placeholder*='Desde' i]").first
    hasta = page.locator("input[placeholder*='Hasta' i]").first
    desde.fill(FECHA_DESDE)
    hasta.fill(FECHA_HASTA)
    llamadas.clear()  # nos interesa lo que dispare la búsqueda
    page.locator("button:has-text('Buscar')").first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(4)
    page.screenshot(path=str(SALIDA / "04_resultados.png"), full_page=True)

    # HTML de la primera fila (para ver los botones de acción)
    filas_html = page.evaluate(
        """() => {
            const filas = [...document.querySelectorAll('table tbody tr')];
            return {num_filas: filas.length,
                    primera_fila: filas.length ? filas[0].outerHTML.slice(0, 8000) : null};
        }"""
    )
    (SALIDA / "primera_fila.html.json").write_text(
        json.dumps(filas_html, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Filas en la grilla: {filas_html['num_filas']}")

    # Intentar expandir/ver acciones de la primera fila: iconos/botones dentro de la fila
    acciones = page.evaluate(
        """() => {
            const fila = document.querySelector('table tbody tr');
            if (!fila) return [];
            return [...fila.querySelectorAll('a, button, i, span[class*=icon], img')].map(e => ({
                tag: e.tagName, clase: e.className, title: e.title || null,
                texto: (e.innerText || '').trim().slice(0, 40) || null
            }));
        }"""
    )
    (SALIDA / "acciones_fila.json").write_text(
        json.dumps(acciones, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (SALIDA / "llamadas_busqueda.json").write_text(
        json.dumps(llamadas, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Llamadas capturadas durante la búsqueda: {len(llamadas)}")
    browser.close()

print(f"Resultados en: {SALIDA.resolve()}")
