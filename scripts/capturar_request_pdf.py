"""Captura el request real de 'Ver PDF' (url, método, headers, post/query)
para poder replicarlo por HTTP y evitar toda la UI."""
import sys, time, json
sys.path.insert(0, "backend")
from app.config import settings
from app.ingesta.siesa_client import SiesaClient

capturados = []

with SiesaClient(settings.url_facturas, settings.username_facturas, settings.password_facturas) as siesa:
    ctx = siesa._context
    def on_req(req):
        if "recepcion" in req.url.lower() and "listado" not in req.url.lower():
            capturados.append({
                "url": req.url, "method": req.method,
                "headers": dict(req.headers),
                "post_data": req.post_data,
            })
    ctx.on("request", on_req)

    docs = siesa.listar_documentos("2026-07-19", "2026-07-22")
    d = docs[0]
    print("doc:", d.folio, d.cufe[:16], "| crudo keys:", list(d.crudo.keys()))
    print("crudo:", json.dumps(d.crudo, ensure_ascii=False)[:600])

    p = siesa.page
    siesa._cerrar_modales()
    caja = p.locator("input[placeholder*='CUFE' i]").first
    caja.fill(""); caja.fill(d.cufe)
    p.locator("button:has-text('Buscar')").first.click()
    p.wait_for_load_state("networkidle", timeout=60000)
    time.sleep(2)
    if p.locator("table tbody tr").count() > 0:
        fila = p.locator("table tbody tr").first
        fila.locator("button.btn-default-drop").click()
        time.sleep(0.5)
        try:
            fila.locator("a:has-text('Ver PDF')").click()
        except Exception as e:
            print("click err:", e)
        time.sleep(10)
    print("\n=== requests 'recepcion' (no listado) capturados ===")
    for c in capturados:
        print(json.dumps(c, ensure_ascii=False, indent=2)[:1500])
        print("----")
