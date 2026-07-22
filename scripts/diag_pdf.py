"""Diagnostica cómo se sirve el PDF: ¿popup nueva pestaña o respuesta en la
página principal? Escucha a nivel de CONTEXTO todas las respuestas y páginas."""
import sys, time
sys.path.insert(0, "backend")
from app.config import settings
from app.ingesta.siesa_client import SiesaClient

respuestas = []
paginas_nuevas = []

with SiesaClient(settings.url_facturas, settings.username_facturas, settings.password_facturas) as siesa:
    ctx = siesa._context
    ctx.on("response", lambda r: respuestas.append((r.url[:80], r.headers.get("content-type",""), r.status)) if "pdf" in r.url.lower() or "recepcion" in r.url.lower() else None)
    ctx.on("page", lambda pg: paginas_nuevas.append(pg))

    docs = siesa.listar_documentos("2026-07-19", "2026-07-22")
    d = docs[6]  # uno fresco que no toqué antes
    print(f"doc elegido: folio={d.folio} cufe={d.cufe[:16]}")

    p = siesa.page
    siesa._cerrar_modales()
    caja = p.locator("input[placeholder*='CUFE' i]").first
    caja.fill(""); caja.fill(d.cufe)
    p.locator("button:has-text('Buscar')").first.click()
    p.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(2)
    filas = p.locator("table tbody tr").count()
    print(f"filas tras buscar por CUFE: {filas}")
    if filas == 0:
        # ¿Quedó algo en la caja o el modal la interfiere?
        print("valor caja CUFE:", caja.input_value())
        print("HTML primeras filas:", p.locator("table tbody").first.inner_text()[:200])
    else:
        fila = p.locator("table tbody tr").first
        fila.locator("button.btn-default-drop").click()
        time.sleep(0.5)
        print("Ver PDF count:", fila.locator("a:has-text('Ver PDF')").count())
        fila.locator("a:has-text('Ver PDF')").click()
        time.sleep(12)  # esperar a ver qué pasa

    print("\n--- respuestas pdf/recepcion capturadas (contexto) ---")
    for r in respuestas:
        print("  ", r)
    print(f"\npáginas nuevas (popups) abiertas: {len(paginas_nuevas)}")
    for pg in paginas_nuevas:
        try:
            print("   popup url:", pg.url)
        except Exception as e:
            print("   popup (sin url):", e)
