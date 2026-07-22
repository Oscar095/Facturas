"""Reproduce el flujo real: listar docs y descargar 3 PDFs seguidos,
imprimiendo el estado de modales VISIBLES entre cada uno."""
import sys, time
sys.path.insert(0, "backend")
from app.config import settings
from app.ingesta.siesa_client import SiesaClient

def modales_visibles(page):
    # uib-modal-window (AngularUI) o bootstrap .modal.in / #modalCheckTD visibles
    return page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('.modal, [uib-modal-window], [role=dialog]').forEach(m => {
            const st = getComputedStyle(m);
            if (st.display !== 'none' && st.visibility !== 'hidden' && m.offsetParent !== null) {
                out.push({id: m.id, cls: m.className, txt: (m.innerText||'').slice(0,80)});
            }
        });
        return out;
    }""")

with SiesaClient(settings.url_facturas, settings.username_facturas, settings.password_facturas) as siesa:
    docs = siesa.listar_documentos("2026-07-13", "2026-07-22")
    print(f"docs listados: {len(docs)}")
    print("modales visibles tras listar:", modales_visibles(siesa.page))
    for i, d in enumerate(docs[:3]):
        print(f"\n=== doc {i}: folio={d.folio} cufe={d.cufe[:14]} ===")
        try:
            pdf = siesa.descargar_pdf(d.cufe)
            print(f"  PDF ok: {len(pdf)} bytes, %PDF={pdf[:4]==b'%PDF'}")
        except Exception as e:
            print(f"  FALLO: {type(e).__name__}: {str(e)[:120]}")
        print("  modales visibles después:", modales_visibles(siesa.page))
