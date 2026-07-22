"""Descubrimiento del portal Siesa Smart4B.

Paso 1: cargar la página de login, volcar los campos del formulario,
intentar login con las credenciales del .env y registrar todas las
llamadas XHR/fetch que hace el SPA (para decidir si automatizamos por
API interna o por UI).

Uso:
    python scripts/explorar_portal.py [carpeta_salida]
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

SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("descargas/exploracion")
SALIDA.mkdir(parents=True, exist_ok=True)

llamadas = []


def registrar_respuesta(res):
    req = res.request
    if req.resource_type in ("xhr", "fetch"):
        item = {
            "metodo": req.method,
            "url": res.url,
            "status": res.status,
            "content_type": res.headers.get("content-type", ""),
        }
        # Guardar cuerpos JSON pequeños para entender la API
        try:
            if "json" in item["content_type"]:
                cuerpo = res.text()
                item["muestra_respuesta"] = cuerpo[:2000]
        except Exception:
            pass
        if req.post_data:
            item["muestra_request"] = req.post_data[:1000]
        llamadas.append(item)


def volcar_inputs(page, nombre):
    campos = page.evaluate(
        """() => [...document.querySelectorAll('input, button, form')].map(e => ({
            tag: e.tagName, type: e.type || null, id: e.id || null,
            name: e.name || null, placeholder: e.placeholder || null,
            formcontrolname: e.getAttribute('formcontrolname'),
            texto: e.tagName === 'BUTTON' ? e.innerText.trim().slice(0, 60) : null,
            visible: !!(e.offsetWidth || e.offsetHeight)
        }))"""
    )
    (SALIDA / f"{nombre}_campos.json").write_text(
        json.dumps(campos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return campos


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale="es-CO")
    page = context.new_page()
    page.on("response", registrar_respuesta)

    print(f"Abriendo {URL} ...")
    page.goto(URL, wait_until="networkidle", timeout=60000)
    time.sleep(3)
    page.screenshot(path=str(SALIDA / "01_login.png"), full_page=True)
    campos = volcar_inputs(page, "01_login")
    print(f"Campos en login: {len(campos)}")

    # Intento de login con selectores genéricos
    exito_login = False
    try:
        caja_usuario = page.locator(
            "input[type='email'], input[type='text'], input[formcontrolname*='user' i], "
            "input[name*='user' i], input[placeholder*='usuario' i], input[placeholder*='correo' i]"
        ).first
        caja_clave = page.locator("input[type='password']").first
        caja_usuario.fill(USUARIO, timeout=10000)
        caja_clave.fill(CLAVE, timeout=10000)
        page.screenshot(path=str(SALIDA / "02_credenciales.png"), full_page=True)
        boton = page.locator(
            "button[type='submit'], button:has-text('Ingresar'), button:has-text('Iniciar'), "
            "button:has-text('Entrar'), button:has-text('Login')"
        ).first
        boton.click(timeout=10000)
        page.wait_for_load_state("networkidle", timeout=45000)
        time.sleep(5)
        exito_login = True
    except Exception as e:
        print(f"Login automático falló: {e}")

    page.screenshot(path=str(SALIDA / "03_post_login.png"), full_page=True)
    volcar_inputs(page, "03_post_login")
    (SALIDA / "url_actual.txt").write_text(page.url, encoding="utf-8")
    print(f"URL actual: {page.url}")
    print(f"Login automático: {'OK' if exito_login else 'FALLÓ'}")

    # Si entramos, navegar un poco para capturar más API (menús visibles)
    if exito_login:
        try:
            enlaces = page.evaluate(
                """() => [...document.querySelectorAll('a, [role=menuitem], .menu-item, li')]
                    .map(e => e.innerText.trim()).filter(t => t && t.length < 60).slice(0, 80)"""
            )
            (SALIDA / "menus.json").write_text(
                json.dumps(enlaces, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    (SALIDA / "llamadas_red.json").write_text(
        json.dumps(llamadas, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Llamadas XHR/fetch capturadas: {len(llamadas)}")
    browser.close()

print(f"Resultados en: {SALIDA.resolve()}")
