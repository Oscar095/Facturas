"""Descubrimiento paso 3:
1. Capturar qué hace el enlace "Ver PDF" de una fila (URL/descarga).
2. Volcar los catálogos de los selects (estado documento, forma de pago, tipo doc).
3. Probar el endpoint de listado directamente (con y sin cookies) con fechas controladas.

Uso:
    python scripts/explorar_portal3.py [carpeta_salida]
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

URL = os.environ["URL_FACTURAS"].strip()
USUARIO = os.environ["USERNAME_FACTURAS"].strip()
CLAVE = os.environ["PASSWORD_FACTURAS"].strip()

SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("descargas/exploracion3")
SALIDA.mkdir(parents=True, exist_ok=True)

API_LISTADO = (
    "https://portalfe.siesacloud.com/PortalPTBack/frontend/web/index.php/"
    "pst/listado/recepcion-proveedores"
)

eventos_red = []


def registrar_respuesta(res):
    if any(d in res.url for d in ("PortalPTBack", "siesafe")):
        eventos_red.append({
            "metodo": res.request.method,
            "url": res.url,
            "status": res.status,
            "content_type": res.headers.get("content-type", ""),
            "request_body": (res.request.post_data or "")[:2000],
        })


def login(page):
    page.goto(URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    page.locator(
        "input[type='email'], input[type='text'], input[name*='user' i], "
        "input[placeholder*='usuario' i], input[placeholder*='correo' i]"
    ).first.fill(USUARIO)
    page.locator("input[type='password']").first.fill(CLAVE)
    page.screenshot(path=str(SALIDA / "login_debug.png"), full_page=True)
    try:
        page.locator(
            "button[type='submit']:visible, button:has-text('Ingresar'):visible"
        ).first.click(timeout=8000)
    except Exception:
        page.locator("input[type='password']").first.press("Enter")
    try:
        page.wait_for_url("**/documentRecepcion/**", timeout=45000)
    except Exception:
        page.screenshot(path=str(SALIDA / "login_fallo.png"), full_page=True)
        raise
    page.wait_for_load_state("networkidle", timeout=45000)
    time.sleep(3)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale="es-CO", accept_downloads=True)
    page = context.new_page()
    page.on("response", registrar_respuesta)

    print("Iniciando sesión...")
    login(page)

    cookies = context.cookies()
    (SALIDA / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    print(f"Cookies de sesión: {[c['name'] for c in cookies]}")

    # Catálogos de los selects
    selects = page.evaluate(
        """() => [...document.querySelectorAll('select')].map(s => ({
            id: s.id || null, name: s.name || null,
            opciones: [...s.options].map(o => ({valor: o.value, texto: o.text.trim()}))
        }))"""
    )
    (SALIDA / "selects.json").write_text(
        json.dumps(selects, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Buscar (rango por defecto = hoy) y abrir el menú de la primera fila
    page.locator("button:has-text('Buscar')").first.click()
    page.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(3)

    fila = page.locator("table tbody tr").first
    fila.locator("button.btn-default-drop").click()
    time.sleep(1)
    eventos_red.clear()

    # "Ver PDF": puede abrir pestaña nueva o descargar
    resultado_pdf = {}
    try:
        with context.expect_page(timeout=8000) as nueva_pagina_info:
            fila.locator("a:has-text('Ver PDF')").click()
        nueva = nueva_pagina_info.value
        try:
            nueva.wait_for_load_state("load", timeout=20000)
        except Exception:
            pass
        resultado_pdf = {"tipo": "pestaña", "url": nueva.url}
    except Exception:
        try:
            with page.expect_download(timeout=10000) as dl_info:
                fila.locator("a:has-text('Ver PDF')").click()
            dl = dl_info.value
            destino = SALIDA / dl.suggested_filename
            dl.save_as(str(destino))
            resultado_pdf = {"tipo": "descarga", "archivo": str(destino), "url": dl.url}
        except Exception as e:
            resultado_pdf = {"tipo": "desconocido", "error": str(e)}
    time.sleep(3)
    (SALIDA / "ver_pdf.json").write_text(
        json.dumps(resultado_pdf, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (SALIDA / "red_ver_pdf.json").write_text(
        json.dumps(eventos_red, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Ver PDF → {resultado_pdf}")

    browser.close()

# ── Prueba del listado por HTTP directo ──────────────────────────────────────
def probar_listado(nombre: str, client: httpx.Client):
    datos = {
        "filters[adquiriente]": "", "filters[consultaVersion]": "2.1",
        "filters[costCentersClient]": "", "filters[cufe]": "",
        "filters[estadoAdquiriente]": "", "filters[estadoDian]": "",
        "filters[facturador]": "", "filters[facturadorSelected]": "",
        "filters[fecha_desde]": "2026-07-01T00:00:00.000Z",
        "filters[fecha_hasta]": "2026-07-17T23:59:59.000Z",
        "filters[folio]": "", "filters[formaPago]": "3",
        "filters[isMaster]": "false", "filters[isOwner]": "false",
        "filters[nit]": "", "filters[nitAdquiriente]": "",
        "filters[operatingCenterId]": "", "filters[tipoDocRecepcion]": "1",
        "id": "", "itemSize": "100", "nit": "901318511", "numPage": "1",
        "userId": "30729",
        "usuarioEvento": "30729;LINA MARIA GARCIA REYES;linag@koscolombia.com",
    }
    r = client.post(API_LISTADO, data=datos, timeout=60)
    resumen = {"status": r.status_code}
    try:
        j = r.json()
        resumen["totalItems"] = j.get("totalItems")
        resumen["primer_folio"] = j["list"][0]["folio"] if j.get("list") else None
    except Exception:
        resumen["texto"] = r.text[:500]
    print(f"Listado directo ({nombre}): {resumen}")
    (SALIDA / f"listado_directo_{nombre}.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if "texto" not in resumen:
        (SALIDA / f"listado_directo_{nombre}_completo.json").write_text(
            r.text, encoding="utf-8"
        )


with httpx.Client() as cliente_sin_cookies:
    probar_listado("sin_cookies", cliente_sin_cookies)

cookies_guardadas = json.loads((SALIDA / "cookies.json").read_text(encoding="utf-8"))
jar = httpx.Cookies()
for c in cookies_guardadas:
    jar.set(c["name"], c["value"], domain=c["domain"])
with httpx.Client(cookies=jar) as cliente_con_cookies:
    probar_listado("con_cookies", cliente_con_cookies)

print(f"Resultados en: {SALIDA.resolve()}")
