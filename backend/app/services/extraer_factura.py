"""Extracción de datos de una factura PDF con Claude — módulo "Cargar factura".

Solo se invoca a petición explícita del usuario (botón "Extraer datos" al cargar
una factura física o de correo): cada llamada consume créditos de API, así que
usa Haiku (el modelo más económico) y envía SOLO el texto del PDF cuando existe
capa de texto (pypdf, gratis); el PDF completo como documento (visión) queda
únicamente para facturas escaneadas sin texto.

El resultado SIEMPRE lo revisa el usuario en el formulario antes de guardar —
la IA no escribe directo en la base de datos.
"""
from __future__ import annotations

import base64
import json
import logging

from ..config import settings

log = logging.getLogger("extraer_factura")

MODELO = "claude-haiku-4-5-20251001"  # el más económico; extraer campos no requiere más
_MAX_TEXTO = 6000  # el encabezado de una factura cabe de sobra; controla el costo
_MIN_TEXTO_UTIL = 150  # menos que esto = PDF escaneado sin capa de texto

CAMPOS = ("nit", "razon_social", "numero", "cufe", "fecha_emision", "valor_total", "iva")

_INSTRUCCION = """Extrae los datos de esta factura electrónica colombiana.
Responde ÚNICAMENTE un JSON válido con exactamente estas claves (usa null si un dato no aparece):
{"nit": "<NIT del EMISOR/proveedor, solo dígitos, SIN el dígito de verificación>",
 "razon_social": "<razón social del EMISOR/proveedor de la factura, no del cliente>",
 "numero": "<número/folio completo de la factura, con su prefijo, ej: FVE12345>",
 "cufe": "<CUFE completo (hash largo hexadecimal) o null si no aparece>",
 "fecha_emision": "<fecha de emisión en formato YYYY-MM-DD>",
 "valor_total": <valor total a pagar, número sin separadores de miles>,
 "iva": <valor del IVA, número, o null>}"""


def disponible() -> bool:
    return bool(settings.anthropic_api_key)


def extraer_datos(pdf: bytes, texto: str | None) -> dict:
    """Devuelve un dict con CAMPOS (valores None si no se encontraron).

    Lanza RuntimeError con mensaje legible si no hay API key o la IA falla —
    el llamador lo convierte en advertencia y el usuario llena el formulario
    a mano (la carga manual nunca depende de que la IA funcione).
    """
    if not disponible():
        raise RuntimeError("No hay API key de IA configurada (API_KEY_IA_CLAUDE)")

    texto = (texto or "").strip()
    if len(texto) >= _MIN_TEXTO_UTIL:
        contenido = [{
            "type": "text",
            "text": f'{_INSTRUCCION}\n\nTexto de la factura (extraído del PDF):\n"""{texto[:_MAX_TEXTO]}"""',
        }]
    else:
        # PDF escaneado: se envía el documento completo (visión, más costoso)
        contenido = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(pdf).decode()}},
            {"type": "text", "text": _INSTRUCCION},
        ]

    try:
        import anthropic

        cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        respuesta = cliente.messages.create(
            model=MODELO,
            max_tokens=500,
            system="Extraes datos estructurados de facturas. Respondes ÚNICAMENTE JSON válido, nada más.",
            messages=[{"role": "user", "content": contenido}],
        )
        crudo = respuesta.content[0].text.strip()
        if crudo.startswith("```"):  # tolerar fences ```json ... ```
            crudo = crudo.strip("`").lstrip("json").strip()
        datos = json.loads(crudo)
    except Exception as e:  # noqa: BLE001 — error legible; el formulario sigue usable
        log.warning("Fallo extrayendo datos de factura con IA: %s", e)
        raise RuntimeError(f"La IA no pudo leer la factura: {e}") from e

    limpio: dict = {}
    for campo in CAMPOS:
        valor = datos.get(campo)
        if isinstance(valor, str):
            valor = valor.strip() or None
        limpio[campo] = valor
    if limpio.get("nit"):
        # solo dígitos: quitar puntos, espacios y el DV si vino como "900123456-7"
        nit = str(limpio["nit"]).split("-")[0]
        limpio["nit"] = "".join(c for c in nit if c.isdigit()) or None
    return limpio
