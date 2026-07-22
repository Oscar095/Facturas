"""Simula el estado atascado (modal + backdrop tapando 'Buscar') y verifica
que descargar_pdf lo limpia solo y logra descargar."""
import sys
sys.path.insert(0, "backend")
from app.config import settings
from app.ingesta.siesa_client import SiesaClient

with SiesaClient(settings.url_facturas, settings.username_facturas, settings.password_facturas) as siesa:
    docs = siesa.listar_documentos("2026-07-13", "2026-07-22")
    d = docs[0]

    # Inyectar un modal uib + backdrop visible que intercepte clics (como el fallo real)
    siesa.page.evaluate("""() => {
        const bd = document.createElement('div');
        bd.className = 'modal-backdrop fade in';
        bd.style = 'z-index:1040;position:fixed;inset:0;background:#000;opacity:.5';
        document.body.appendChild(bd);
        const m = document.createElement('div');
        m.setAttribute('uib-modal-window','modal-window');
        m.className = 'modal fade in';
        m.style = 'z-index:1050;display:block;position:fixed;inset:0';
        m.innerHTML = '<div class="modal-dialog"><div class="modal-content">'
            + '<button class="close" data-dismiss="modal">x</button>ATASCADO</div></div>';
        document.body.appendChild(m);
    }""")
    vis = siesa.page.evaluate("() => document.querySelectorAll('[uib-modal-window], .modal-backdrop').length")
    print(f"modales/backdrops inyectados (deben ser 2): {vis}")

    try:
        pdf = siesa.descargar_pdf(d.cufe)
        print(f"RECUPERADO -> PDF ok: {len(pdf)} bytes, %PDF={pdf[:4]==b'%PDF'}")
    except Exception as e:
        print(f"NO recuperó: {type(e).__name__}: {str(e)[:150]}")

    restante = siesa.page.evaluate("() => document.querySelectorAll('.modal-backdrop').length")
    print(f"backdrops restantes tras descargar (debe ser 0): {restante}")
