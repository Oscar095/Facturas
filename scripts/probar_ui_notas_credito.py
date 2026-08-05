"""UI: asignar el área de una nota crédito desde el listado y verla reflejada.

Deja la nota como estaba (la devuelve a "sin asignar" por API al terminar).
Requiere el backend corriendo en 127.0.0.1:8000 sirviendo frontend/dist.
"""
import sys

sys.path.insert(0, "backend")

import httpx  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8000"
EMAIL, CLAVE = "oscar.orozco03@gmail.com", "Admin1234*"

errores = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context().new_page()
    page.on("console", lambda m: errores.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errores.append(str(e)))

    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill("input[type=email]", EMAIL)
    page.fill("input[type=password]", CLAVE)
    page.click("button:has-text('Ingresar')")
    page.wait_for_selector(".sidebar, .app-shell", timeout=15000)

    # el link del menú debe existir (ya no está detrás de ver_todas_areas)
    expect(page.locator(".sidebar a", has_text="Notas Crédito")).to_have_count(1, timeout=8000)
    print("1) link 'Notas Crédito' visible en el menú: OK")

    page.click(".sidebar a:has-text('Notas Crédito')")
    page.wait_for_selector("h1:has-text('Notas Crédito')", timeout=10000)
    # esperar los datos: mientras carga, el tbody tiene una sola fila "Cargando…"
    page.wait_for_selector("table.tabla tbody tr select.select-area", timeout=15000)
    filas = page.locator("table.tabla tbody tr")
    print(f"2) listado renderizado con {filas.count()} filas: OK")

    # la columna Área trae un dropdown por fila (permiso editar_facturas)
    selects = page.locator("table.tabla tbody tr select.select-area")
    print(f"3) dropdown de área en {selects.count()} filas: OK")

    # asignar el área a la primera nota
    numero = filas.first.locator("td").first.inner_text().strip()
    primer_select = selects.first
    opciones = primer_select.locator("option:not([disabled])")
    area_texto = opciones.first.inner_text().strip()
    primer_select.select_option(index=1)

    # tras el PATCH, el select queda con esa área seleccionada
    expect(primer_select).to_have_value(opciones.first.get_attribute("value"), timeout=10000)
    print(f"4) área '{area_texto}' asignada a la nota {numero} desde la UI: OK")

    # el filtro "Solo sin área" ya no debe traerla
    page.check("input[type=checkbox]")
    page.wait_for_timeout(1500)
    sin_area = page.locator("table.tabla tbody tr", has_text=numero)
    expect(sin_area).to_have_count(0, timeout=8000)
    print(f"5) filtro 'Solo sin área' ya no muestra la nota {numero}: OK")

    err_ui = page.locator(".error")
    print("   errores en pantalla:", err_ui.inner_text() if err_ui.count() else "ninguno")
    page.screenshot(path="notas-credito-area.png", full_page=True)
    b.close()

print("\nerrores de consola:", errores or "ninguno")

# limpieza: devolver la nota a "sin asignar"
c = httpx.Client(base_url=BASE, timeout=30)
r = c.post("/api/auth/login", data={"username": EMAIL, "password": CLAVE})
r.raise_for_status()
c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
nota = next(n for n in c.get("/api/notas-credito").json()["items"] if n["numero"] == numero)
sys.path.insert(0, "backend")
from app.database import SessionLocal  # noqa: E402
from app.models import NotaCredito  # noqa: E402
db = SessionLocal()
n = db.get(NotaCredito, nota["id"])
n.area_id, n.responsable_id = None, None
db.commit()
db.close()
print(f"limpieza: la nota {numero} vuelve a 'sin asignar'")
print("\nOK: la UI de notas crédito asigna área correctamente")
