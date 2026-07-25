"""Unitario: estampar en un PDF de 4 páginas con tamaños mezclados
(carta vertical, carta horizontal) -> el sello debe quedar en TODAS."""
import sys
sys.path.insert(0, "backend")
from io import BytesIO
from PIL import Image, ImageDraw
from pypdf import PdfReader
from reportlab.pdfgen import canvas as rl
from app.services.firmar_pdf import estampar_firma

img = Image.new("RGBA", (400, 140), (0, 0, 0, 0))
ImageDraw.Draw(img).line([(20, 100), (140, 40), (260, 100)], fill=(25, 35, 95, 255), width=6)
b = BytesIO(); img.save(b, "PNG")

pb = BytesIO()
c = rl.Canvas(pb)
for i, tam in enumerate([(612, 792), (612, 792), (792, 612), (612, 792)]):
    c.setPageSize(tam)
    c.drawString(72, tam[1] - 72, f"pagina {i+1} ({'horizontal' if tam[0] > tam[1] else 'vertical'})")
    c.showPage()
c.save()

sellado = estampar_firma(pb.getvalue(), b.getvalue(), "Aprobado por Prueba — 24/07/2026 10:00")
lector = PdfReader(BytesIO(sellado))
assert len(lector.pages) == 4
for i, pag in enumerate(lector.pages):
    t = pag.extract_text() or ""
    assert "Aprobado por" in t, f"página {i+1} sin sello"
    assert "/XObject" in pag.get("/Resources", {}), f"página {i+1} sin imagen"
    print(f"  página {i+1} ({float(pag.mediabox.width):.0f}x{float(pag.mediabox.height):.0f}): sello OK")
print("unitario multi-tamaño: OK")
