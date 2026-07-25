"""Extracción de texto de los PDF de factura (local, sin IA).

Los PDF del portal Siesa son generados digitalmente (no escaneados), así que
pypdf extrae el texto de los ítems/conceptos de forma confiable. Ese texto se
guarda en `facturas.texto_pdf` y es la base sobre la que se evalúan los
patrones de ítem de las reglas de área.
"""
from __future__ import annotations

import io
import logging

log = logging.getLogger("pdf_texto")

_MAX_PAGINAS = 5  # los ítems van al inicio; no hace falta leer anexos largos


def extraer_texto(pdf_bytes: bytes) -> str:
    """Devuelve el texto plano del PDF ('' si no se puede extraer)."""
    try:
        from pypdf import PdfReader

        lector = PdfReader(io.BytesIO(pdf_bytes))
        partes = []
        for pagina in lector.pages[:_MAX_PAGINAS]:
            partes.append(pagina.extract_text() or "")
        return "\n".join(partes).strip()
    except Exception as e:  # noqa: BLE001 — un PDF raro no debe tumbar la ingesta
        log.warning("No se pudo extraer texto del PDF: %s", e)
        return ""
