"""Extracción del IVA desde el texto del PDF (sin IA, gratis).

El portal Siesa **no expone el IVA ni la base gravable**: el JSON del listado
tiene 23 claves y solo trae `valor` (el total). Verificado con un spike sobre el
portal real — no volver a intentarlo a ciegas. Como el seguimiento del negocio
se hace sin IVA, hay que deducirlo del texto que ya extraemos con pypdf
(`facturas.texto_pdf`).

La clave del método es que **el total ya se conoce**, así que no hace falta
entender el layout (que es caótico: cada proveedor imprime distinto, con
separadores de miles en punto o en coma, columnas revueltas y retenciones
mezcladas). Basta con aritmética:

  1. A una tarifa legal el IVA está determinado: `iva = total * r / (1 + r)`.
     Se acepta solo si ese importe **aparece impreso** en la factura. Es una
     validación de doble filo (reconcilia con el total Y está escrito), así que
     los falsos positivos son casi imposibles.
  2. Si el total aparece etiquetado como subtotal / base gravable / total bruto,
     la factura no lleva IVA -> 0. (Ojo: el "Total a pagar" puede ser MENOR que
     el subtotal por retenciones —retefuente, reteica—, que NO son IVA.)

Lo que no encaje en esos dos niveles se deja en None: es preferible una factura
sin IVA discriminado a un subtotal inventado. Cobertura medida sobre los PDF
reales de la BD: ~79%.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Tarifas de IVA vigentes en Colombia. NO agregar 8% (eso es impoconsumo, no
# IVA) ni 16% (derogada): en los datos reales solo sumaban coincidencias.
TARIFAS = (Decimal("0.19"), Decimal("0.05"))

# Margen para el redondeo del proveedor al imprimir (centavos vs pesos).
_TOLERANCIA = Decimal("2")

_CENTAVOS = Decimal("0.01")

_NUMERO = re.compile(r"\d[\d.,]*\d|\d")

# Etiquetas del valor ANTES de impuestos. "Total bruto"/"valor bruto" en las
# facturas colombianas es la base, no el total a pagar.
_ETIQUETA_BASE = re.compile(
    r"sub\s*-?\s*total|base\s+grav|total\s+bruto|valor\s+bruto|total\s+valor\s+bruto",
    re.IGNORECASE,
)
_VENTANA_BASE = 90  # chars tras la etiqueta donde puede estar su valor


def _numeros(texto: str) -> set[Decimal]:
    """Todos los importes del texto, en sus DOS lecturas posibles.

    Conviven "1.190.000,50" (miles con punto) y "1,190,000.50" (miles con coma)
    en el mismo universo de proveedores, y a veces en la misma factura. En vez
    de adivinar la convención se generan ambas interpretaciones: la
    comprobación aritmética contra el total desempata sola.
    """
    valores: set[Decimal] = set()
    for m in _NUMERO.finditer(texto):
        crudo = m.group(0).strip(".,")
        if not crudo:
            continue
        for sep_miles, sep_dec in ((".", ","), (",", ".")):
            try:
                v = Decimal(crudo.replace(sep_miles, "").replace(sep_dec, "."))
            except InvalidOperation:
                continue
            if v >= 0:
                valores.add(v)
    return valores


def _cerca(valores: set[Decimal], objetivo: Decimal) -> bool:
    return any(abs(v - objetivo) <= _TOLERANCIA for v in valores)


def extraer_iva(texto: str | None, valor_total: Decimal | None) -> Decimal | None:
    """IVA de la factura en COP, o None si no se puede determinar con certeza."""
    if not texto or valor_total is None or valor_total <= 0:
        return None

    plano = re.sub(r"\s+", " ", texto)
    numeros = _numeros(plano)

    # 1) tarifa legal reconciliada contra el total
    for tarifa in TARIFAS:
        teorico = (valor_total * tarifa / (1 + tarifa)).quantize(_CENTAVOS)
        if _cerca(numeros, teorico):
            return teorico

    # 2) el total impreso como base/subtotal => la factura no lleva IVA
    for m in _ETIQUETA_BASE.finditer(plano):
        if _cerca(_numeros(plano[m.end():m.end() + _VENTANA_BASE]), valor_total):
            return Decimal("0.00")

    return None


def resolver_iva(texto: str | None, valor_total: Decimal | None,
                 pdf: bytes | None = None,
                 usar_ia: bool = False) -> tuple[Decimal | None, bool]:
    """Cascada completa: aritmética (gratis) y, como ÚLTIMO recurso, IA.

    Devuelve (iva, uso_ia). La IA solo se consulta si `usar_ia` y los dos
    niveles determinísticos no decidieron — el mismo criterio que la asignación
    de área y el vencimiento: primero lo gratis, la IA nunca por defecto.
    """
    iva = extraer_iva(texto, valor_total)
    if iva is not None or not usar_ia:
        return iva, False

    from . import iva_ia  # import local: solo se carga si se usa IA

    iva = iva_ia.sugerir_iva(pdf, texto, valor_total)
    return iva, iva is not None


def subtotal(valor_total: Decimal | None, iva: Decimal | None) -> Decimal | None:
    """Valor sin IVA. Con IVA desconocido devuelve el total tal cual: el
    consumidor debe distinguirlo por `iva is None` (la UI lo marca)."""
    if valor_total is None:
        return None
    return valor_total - (iva or Decimal(0))
