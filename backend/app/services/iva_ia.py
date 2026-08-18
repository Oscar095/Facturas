"""Último recurso para el IVA: preguntarle a Claude (Haiku).

Solo se invoca cuando `services/iva.py` (dos niveles aritméticos, gratis) no
pudo determinarlo. Diseñado para gastar lo mínimo posible:

  - Prompt corto y respuesta de una línea (`base|iva|cita` o `NULL`).
  - Si el PDF tiene capa de texto se manda SOLO el texto recortado, y se manda
    el final además del principio: el bloque de totales va al pie del documento.
  - Si viene escaneado se manda el PDF como documento (visión, más caro) pero
    **recortado a la primera y la última página**: los totales están en la
    última, y el costo de visión escala por página.

Guardarraíles contra la invención (ver `_aceptable`), que son el corazón de
este módulo: pedirle a un modelo el IVA de una factura que no lo discrimina lo
empuja a "completar" con el 19% de rigor. Nunca lanza: ante cualquier fallo
devuelve None y la factura queda sin IVA (marcada en la UI), que es preferible
a un subtotal inventado.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from decimal import Decimal, InvalidOperation

from ..config import settings
from .iva import _TOLERANCIA, _numeros

log = logging.getLogger("iva_ia")

MODELO = "claude-haiku-4-5-20251001"  # el más económico
_MAX_TEXTO = 6000       # principio + final: el bloque de totales va al pie
_MIN_TEXTO_UTIL = 150   # menos que esto = PDF escaneado, toca visión

# Tarifa máxima admisible sobre la base. El IVA en Colombia llega al 19%; se
# deja un margen mínimo para redondeos, pero no tanto como para dejar pasar un
# gravamen arancelario o un flete (que en las facturas de importación conviven
# con la palabra "IVA" y superan holgadamente ese porcentaje).
_TARIFA_MAXIMA = Decimal("0.20")

_INSTRUCCION = (
    "De esta factura necesito DOS cifras, tal como están IMPRESAS:\n"
    "  - la BASE (subtotal antes de IVA)\n"
    "  - el IVA (impuesto sobre las ventas)\n"
    "NO calcules ni asumas el 19%: si la factura no discrimina el IVA, responde NULL.\n"
    "No confundas el IVA con retenciones (reteiva, retefuente, reteica), ni con otros "
    "impuestos (impoconsumo, gravamen arancelario), ni con fletes, seguros o manejo.\n"
    "Ojo con los separadores: 1.190.000,50 y 1,190,000.50 son el mismo número.\n"
    "Responde en UNA línea: base|iva|<el fragmento LITERAL del documento de donde "
    "los sacaste>  —  o solo NULL."
)


def disponible() -> bool:
    return bool(settings.anthropic_api_key)


def _candidatos(txt: str) -> list[Decimal]:
    """Lecturas posibles de un importe, sin desempatar.

    "104200.00" son 104.200 con decimales, pero también podría leerse como
    10.420.000 si el punto fuera separador de miles. NO se elige aquí (elegir
    "la mayor" leía 104.200,00 como 10.420.000): se devuelven todas las lecturas
    plausibles y la comprobación aritmética contra el total decide cuál era,
    igual que en `iva.py`.

    El modelo mezcla convenciones e incluso las combina ("680.943.00" = punto de
    miles Y punto decimal), así que además de las dos convenciones clásicas se
    prueba: tomar el último separador como decimal, y tratarlos todos como miles.
    """
    crudo = re.sub(r"[^\d.,]", "", txt or "").strip(".,")
    if not crudo:
        return []

    lecturas: set[str] = set()
    # (a) el último separador es el decimal si deja 1-2 dígitos detrás
    m = re.search(r"[.,](\d{1,2})$", crudo)
    if m:
        lecturas.add(re.sub(r"[.,]", "", crudo[:m.start()]) + "." + m.group(1))
    # (b) todos los separadores son de miles
    lecturas.add(re.sub(r"[.,]", "", crudo))
    # (c) las dos convenciones clásicas
    for sep_miles, sep_dec in ((".", ","), (",", ".")):
        cand = crudo.replace(sep_miles, "").replace(sep_dec, ".")
        if cand.count(".") <= 1:
            lecturas.add(cand)

    vistos: list[Decimal] = []
    for lectura in lecturas:
        try:
            v = Decimal(lectura)
        except InvalidOperation:
            continue
        if v >= 0 and v not in vistos:
            vistos.append(v)
    return vistos


def _cifras(partes: list[str]) -> tuple[list[Decimal], list[Decimal]]:
    """Las dos primeras cifras de la respuesta, saltando lo que no sea numérico.

    El modelo a veces repite las etiquetas del formato pedido
    ("base|iva|20,000.00|0.00"), así que no se puede asumir que las cifras estén
    en las posiciones 0 y 1.
    """
    numericas = [c for c in (_candidatos(p) for p in partes) if c]
    if len(numericas) < 2:
        return [], []
    return numericas[0], numericas[1]


def _recorte(texto: str) -> str:
    """Principio + final del texto: la cabecera identifica, el pie tiene los totales."""
    if len(texto) <= _MAX_TEXTO:
        return texto
    mitad = _MAX_TEXTO // 2
    return f"{texto[:mitad]}\n[…]\n{texto[-mitad:]}"


def _paginas_utiles(pdf: bytes) -> bytes:
    """Recorta el PDF a la primera y la última página (control de costo)."""
    try:
        from pypdf import PdfReader, PdfWriter

        lector = PdfReader(io.BytesIO(pdf))
        if len(lector.pages) <= 2:
            return pdf
        escritor = PdfWriter()
        escritor.add_page(lector.pages[0])
        escritor.add_page(lector.pages[-1])
        buf = io.BytesIO()
        escritor.write(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — si no se puede recortar, se manda completo
        return pdf


def _aceptable(base: Decimal, iva: Decimal, valor_total: Decimal,
               texto: str, hay_texto: bool) -> bool:
    """¿La respuesta del modelo está sustentada, o se la inventó?

    Tres filtros, en orden de fuerza:

    1. `base + iva == total`. El total lo entrega el portal, no el modelo, así
       que una lectura mal hecha se cae aquí (comprobado: en una factura de 73
       millones el modelo devolvió el IVA de UN renglón; la suma lo delató).
       Ojo con su punto ciego: un IVA de 0 con base = total cumple siempre, así
       que ahí la suma no protege. Se acepta igual —el modelo está LEYENDO un
       "IVA $ 0" impreso, no calculándolo, y el valor mostrado al usuario es el
       mismo que si quedara sin determinar— pero es la respuesta más frágil.
    2. Tarifa entre 0 y `_TARIFA_MAXIMA`. Descarta que haya tomado el gravamen
       arancelario o el flete de una factura de importación.
    3. Si hay capa de texto, el importe del IVA debe **aparecer impreso**. Es el
       guardarraíl decisivo: la vía gratis ya descartó que ese importe sea el de
       una tarifa legal, así que si además NO está escrito, el modelo lo calculó
       en vez de leerlo. En las escaneadas no aplica — no hay texto que
       confrontar — y ahí se confía en la visión.
    """
    if iva < 0 or base <= 0:
        return False
    if abs(base + iva - valor_total) > _TOLERANCIA:
        return False
    if iva / base > _TARIFA_MAXIMA:
        return False
    # El literal solo se exige para un IVA positivo: un "0" está en cualquier
    # factura y comprobarlo no aportaría nada.
    if hay_texto and iva > 0 and not any(abs(v - iva) <= _TOLERANCIA for v in _numeros(texto)):
        return False
    return True


def sugerir_iva(pdf: bytes | None, texto: str | None,
                valor_total: Decimal | None) -> Decimal | None:
    """IVA de la factura según la IA, o None si no lo dice o no convence."""
    if not disponible() or valor_total is None or valor_total <= 0:
        return None

    texto = (texto or "").strip()
    hay_texto = len(texto) >= _MIN_TEXTO_UTIL
    instruccion = f"{_INSTRUCCION}\nEl total de esta factura es {valor_total}."
    if hay_texto:
        contenido = [{"type": "text",
                      "text": f'{instruccion}\n\nTexto de la factura:\n"""{_recorte(texto)}"""'}]
    elif pdf:
        contenido = [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(_paginas_utiles(pdf)).decode()}},
            {"type": "text", "text": instruccion},
        ]
    else:
        return None  # sin texto y sin PDF no hay nada que leer

    try:
        import anthropic

        cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        respuesta = cliente.messages.create(
            model=MODELO,
            max_tokens=80,  # dos cifras + el fragmento citado
            system="Extraes dos cifras de facturas. Respondes SOLO 'base|iva|cita' o NULL.",
            messages=[{"role": "user", "content": contenido}],
        )
        crudo = respuesta.content[0].text.strip().strip(".`\"' ")
    except Exception as e:  # noqa: BLE001 — la IA nunca debe tumbar la ingesta
        log.warning("Fallo consultando IA para el IVA: %s", e)
        return None

    if not crudo or crudo.upper().startswith("NULL"):
        return None

    partes = crudo.split("|")
    if len(partes) < 2:
        log.warning("La IA devolvió una respuesta ilegible para el IVA: %r", crudo)
        return None
    bases, ivas = _cifras(partes)
    if not bases or not ivas:
        log.warning("La IA devolvió cifras ilegibles: %r", crudo)
        return None

    # Se prueban las lecturas posibles de cada cifra y se acepta la combinación
    # que reconcilie con el total; si ninguna lo hace, no hubo respaldo.
    for base in bases:
        for iva in ivas:
            if _aceptable(base, iva, valor_total, texto, hay_texto):
                return iva.quantize(Decimal("0.01"))
    log.warning("IVA descartado por falta de respaldo — total %s, respuesta %r",
                valor_total, crudo[:80])
    return None
