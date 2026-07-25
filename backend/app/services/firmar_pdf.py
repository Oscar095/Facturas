"""Estampado de la firma del aprobador en los PDF de la factura.

La firma (imagen del usuario) se coloca en TODAS las páginas del documento,
esquina inferior derecha, con una línea de texto debajo ("Aprobado por … —
fecha"). Se genera una página-overlay con reportlab (una por cada tamaño de
página distinto) y se fusiona con pypdf; el PDF original no se modifica en el
Blob (el sellado se sube como archivo nuevo).
"""
from __future__ import annotations

from io import BytesIO

# Tamaño y posición del sello (puntos PDF; 72 pt = 1 pulgada)
_ANCHO_FIRMA = 150.0
_ALTO_MAX = 60.0
_MARGEN = 36.0


def estampar_firma(pdf_bytes: bytes, imagen_firma: bytes, texto: str) -> bytes:
    """Devuelve el PDF con la firma estampada en todas las páginas (abajo a la derecha)."""
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    lector = PdfReader(BytesIO(pdf_bytes))

    img = ImageReader(BytesIO(imagen_firma))
    iw, ih = img.getSize()
    ancho = _ANCHO_FIRMA
    alto = ancho * ih / iw
    if alto > _ALTO_MAX:  # firmas muy "altas": limitar para no tapar contenido
        alto = _ALTO_MAX
        ancho = alto * iw / ih

    # un overlay por cada tamaño de página (se reutiliza si todas miden igual)
    overlays: dict[tuple[float, float], object] = {}
    for pagina in lector.pages:
        ancho_pag = float(pagina.mediabox.width)
        alto_pag = float(pagina.mediabox.height)
        clave = (round(ancho_pag, 2), round(alto_pag, 2))
        if clave not in overlays:
            x = ancho_pag - ancho - _MARGEN
            y = _MARGEN + 12  # deja sitio para la línea de texto debajo
            buf = BytesIO()
            c = canvas.Canvas(buf, pagesize=(ancho_pag, alto_pag))
            c.drawImage(img, x, y, width=ancho, height=alto, mask="auto")
            c.setFont("Helvetica", 7.5)
            c.drawRightString(ancho_pag - _MARGEN, y - 9, texto)
            c.save()
            buf.seek(0)
            overlays[clave] = PdfReader(buf).pages[0]
        pagina.merge_page(overlays[clave])

    salida = PdfWriter()
    for pagina in lector.pages:
        salida.add_page(pagina)
    out = BytesIO()
    salida.write(out)
    return out.getvalue()
