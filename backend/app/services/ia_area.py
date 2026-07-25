"""Asignación de área con IA (Claude) — ÚLTIMA opción, para no gastar créditos.

Solo se invoca cuando las reglas determinísticas no deciden: el proveedor tiene
varias áreas candidatas y ningún patrón de ítem coincidió con el texto del PDF.
Usa Haiku (el modelo más económico) con el texto truncado. Sin API key
configurada (API_KEY_IA_CLAUDE), no hace nada.
"""
from __future__ import annotations

import json
import logging

from ..config import settings

log = logging.getLogger("ia_area")

MODELO = "claude-haiku-4-5-20251001"  # el más económico; clasificar no requiere más
_MAX_TEXTO = 4000  # los ítems van al inicio del PDF; truncar controla el costo


def disponible() -> bool:
    return bool(settings.anthropic_api_key)


def sugerir_area(
    texto_factura: str,
    proveedor: str,
    candidatas: list[tuple[int, str, list[str]]],
) -> tuple[int | None, str]:
    """Pide a Claude elegir el área entre las candidatas del proveedor.

    candidatas: [(area_id, nombre_area, patrones_conocidos)].
    Devuelve (area_id | None, razón). Nunca lanza: ante cualquier error
    devuelve (None, motivo) y la factura queda sin asignar.
    """
    if not disponible():
        return None, "sin API key de IA configurada"
    try:
        import anthropic

        cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        lineas = "\n".join(
            f"- id={aid}: {nombre}" + (f" (pistas de ítems: {', '.join(pistas)})" if pistas else "")
            for aid, nombre, pistas in candidatas
        )
        respuesta = cliente.messages.create(
            model=MODELO,
            max_tokens=200,
            system=(
                "Clasificas facturas de proveedores en el área responsable de la "
                "empresa. Respondes ÚNICAMENTE un JSON válido, nada más."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Proveedor: {proveedor}\n"
                    f"Áreas candidatas (elige exactamente una por su id, o null si "
                    f"el texto no permite decidir con seguridad):\n{lineas}\n\n"
                    f"Texto de la factura (extraído del PDF):\n"
                    f'"""{(texto_factura or "")[:_MAX_TEXTO]}"""\n\n'
                    'Responde solo: {"area_id": <id o null>, "razon": "<máx 20 palabras>"}'
                ),
            }],
        )
        crudo = respuesta.content[0].text.strip()
        # tolerar fences ```json ... ```
        if crudo.startswith("```"):
            crudo = crudo.strip("`").lstrip("json").strip()
        datos = json.loads(crudo)
        area_id = datos.get("area_id")
        razon = str(datos.get("razon", ""))[:300]
        ids_validos = {aid for aid, _, _ in candidatas}
        if isinstance(area_id, int) and area_id in ids_validos:
            return area_id, razon
        return None, razon or "la IA no pudo decidir"
    except Exception as e:  # noqa: BLE001 — la IA nunca debe tumbar la ingesta
        log.warning("Fallo consultando IA para área: %s", e)
        return None, f"error IA: {e}"
