"""Último recurso para la fecha de vencimiento: preguntarle a Claude (Haiku).

Solo se invoca cuando `services/vencimiento.py` (3 niveles de regex, gratis) no
pudo deducirla. Diseñado para gastar lo mínimo posible:

  - Prompt corto y respuesta de una línea (`AAAA-MM-DD` o `NULL`).
  - Si el PDF tiene capa de texto se manda SOLO el texto recortado.
  - Si viene escaneado se manda el PDF como documento (visión, más caro) pero
    **recortado a la primera página**: el vencimiento va siempre en el
    encabezado, y el costo de visión escala por página.
  - Valida la respuesta contra la fecha de emisión igual que el extractor
    determinístico: si la IA devuelve algo incoherente, se descarta.

Nunca lanza: ante cualquier fallo devuelve None y la factura queda sin
vencimiento (mismo criterio que el resto: no adivinar).
"""
from __future__ import annotations

import base64
import io
import logging
import re
from datetime import datetime, timedelta

from ..config import settings
from .vencimiento import _MAX_DIAS, _fechas_en

log = logging.getLogger("vencimiento_ia")

MODELO = "claude-haiku-4-5-20251001"  # el más económico
_MAX_TEXTO = 4000       # el encabezado de la factura cabe de sobra
_MIN_TEXTO_UTIL = 150   # menos que esto = PDF escaneado, toca visión
_PAGINAS_VISION = 1     # el vencimiento va en el encabezado; 1 página basta

_INSTRUCCION = (
    "¿Cuál es la fecha de VENCIMIENTO (fecha límite de pago) de esta factura?\n"
    "No la confundas con la fecha de emisión ni con la vigencia de la resolución DIAN.\n"
    "Si la factura solo indica el plazo (ej. 'crédito 30 días'), súmalo a la emisión.\n"
    "NO ADIVINES: si la fecha no está escrita ni hay un plazo explícito, responde NULL. "
    "Nunca asumas un plazo típico de 30 días.\n"
    "Responde en una línea: AAAA-MM-DD|<el fragmento LITERAL del documento de donde "
    "la sacaste>  —  o solo NULL."
)

_PLAZO_DIAS = re.compile(r"\b(\d{1,3})\s*d[ií]as", re.IGNORECASE)


def _parsear_fecha(txt: str) -> datetime | None:
    """AAAA-MM-DD es lo que se pide, pero el modelo a veces responde en el
    formato de la factura (DD/MM/AAAA); se aceptan ambos antes de descartar."""
    try:
        return datetime.fromisoformat(txt[:10])
    except ValueError:
        pass
    candidatas = _fechas_en(txt)
    return candidatas[0] if candidatas else None


def _respaldada_por_el_documento(venc: datetime, texto: str,
                                 fecha_emision: datetime | None) -> bool:
    """¿La fecha que devolvió la IA está realmente sustentada en el documento?

    Guardarraíl contra la invención: observado en pruebas, ante una factura que
    no dice el vencimiento el modelo tiende a "completar" con el plazo típico de
    30 días. Se acepta la respuesta solo si la fecha aparece impresa en el texto,
    o si sale de sumar a la emisión un plazo que sí está escrito ("crédito 45
    días"). No aplica a facturas escaneadas: ahí no hay texto que confrontar.
    """
    if venc in set(_fechas_en(texto)):
        return True
    if fecha_emision is not None:
        for m in _PLAZO_DIAS.finditer(texto):
            if fecha_emision + timedelta(days=int(m.group(1))) == venc:
                return True
    return False


def disponible() -> bool:
    return bool(settings.anthropic_api_key)


def _primera_pagina(pdf: bytes) -> bytes:
    """Recorta el PDF a la primera página (control de costo en visión)."""
    try:
        from pypdf import PdfReader, PdfWriter

        lector = PdfReader(io.BytesIO(pdf))
        if len(lector.pages) <= _PAGINAS_VISION:
            return pdf
        escritor = PdfWriter()
        for i in range(_PAGINAS_VISION):
            escritor.add_page(lector.pages[i])
        buf = io.BytesIO()
        escritor.write(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — si no se puede recortar, se manda completo
        return pdf


def sugerir_vencimiento(pdf: bytes | None, texto: str | None,
                        fecha_emision: datetime | None) -> datetime | None:
    """Devuelve la fecha de vencimiento según la IA, o None."""
    if not disponible():
        return None

    texto = (texto or "").strip()
    hay_texto = len(texto) >= _MIN_TEXTO_UTIL
    if hay_texto:
        contenido = [{
            "type": "text",
            "text": f'{_INSTRUCCION}\n\nTexto de la factura:\n"""{texto[:_MAX_TEXTO]}"""',
        }]
    elif pdf:
        contenido = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(_primera_pagina(pdf)).decode()}},
            {"type": "text", "text": _INSTRUCCION},
        ]
    else:
        return None  # sin texto y sin PDF no hay nada que leer

    if fecha_emision is not None:
        contenido[-1]["text"] += (
            f"\nLa factura fue emitida el {fecha_emision.date().isoformat()}."
        )

    try:
        import anthropic

        cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        respuesta = cliente.messages.create(
            model=MODELO,
            max_tokens=60,  # una fecha + el fragmento citado
            system="Extraes un solo dato de facturas. Respondes SOLO 'fecha|cita' o NULL.",
            messages=[{"role": "user", "content": contenido}],
        )
        crudo = respuesta.content[0].text.strip().strip(".`\"' ")
    except Exception as e:  # noqa: BLE001 — la IA nunca debe tumbar la ingesta
        log.warning("Fallo consultando IA para vencimiento: %s", e)
        return None

    if not crudo or crudo.upper().startswith("NULL"):
        return None
    fecha_txt, _, cita = crudo.partition("|")
    venc = _parsear_fecha(fecha_txt.strip())
    if venc is None:
        log.warning("La IA devolvió una fecha ilegible: %r", crudo)
        return None

    # Anti-invención (ver _respaldada_por_el_documento)
    if hay_texto and not _respaldada_por_el_documento(venc, texto, fecha_emision):
        log.warning("La IA propuso %s sin respaldo en la factura (citó %r) — descartado",
                    venc.date(), cita.strip()[:50])
        return None

    # Misma sanidad que el extractor determinístico: nunca antes de la emisión
    # ni más allá del plazo máximo razonable (evita la vigencia de resolución).
    if fecha_emision is not None:
        if not (fecha_emision - timedelta(days=1) <= venc
                <= fecha_emision + timedelta(days=_MAX_DIAS)):
            log.warning("La IA devolvió %s, incoherente con la emisión %s",
                        venc.date(), fecha_emision.date())
            return None
    return venc
