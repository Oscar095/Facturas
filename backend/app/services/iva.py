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
  2. Tarifa MIXTA (parte gravada, parte exenta): la tarifa global no es 19% ni
     5%, así que el nivel 1 no las ve. Se busca un importe etiquetado como IVA
     cuya **base (total - iva) también esté impresa**; ahí la aritmética vuelve a
     hacer de doble validación.
  3. Si el total aparece etiquetado como subtotal / base gravable / total bruto,
     la factura no lleva IVA -> 0. (Ojo: el "Total a pagar" puede ser MENOR que
     el subtotal por retenciones —retefuente, reteica—, que NO son IVA.)

Lo que no encaje en esos tres niveles se deja en None: es preferible una factura
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

# Etiqueta del IVA mismo, para el nivel 2 (tarifa mixta). NO se usa para tomar
# "el número que sigue a IVA" a ciegas —eso ya se probó y en las facturas de
# importación elegía el flete o el gravamen arancelario—: el importe solo se
# acepta si su base (total - iva) también está impresa.
_ETIQUETA_IVA = re.compile(r"\bi\.?\s*v\.?\s*a\.?\b", re.IGNORECASE)
_VENTANA_IVA = 40
# Por debajo de esto un "IVA" candidato es ruido: la tolerancia de 2 pesos deja
# pasar importes minúsculos (base ~= total), y el número pegado a la etiqueta
# suele ser la tarifa ("IVA 19.00 %").
_IVA_MINIMO = Decimal("100")
# Ninguna tarifa legal llega al 20%: descarta gravámenes arancelarios y fletes.
_TARIFA_MAXIMA = Decimal("0.20")


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


def a_decimal(valor) -> Decimal | None:
    """Normaliza el total a Decimal.

    Imprescindible: la BD entrega `valor_total` como Decimal, pero la INGESTA lo
    pasa como float (`_a_float` en siesa_client), y mezclar float con Decimal
    revienta con TypeError. Se convierte vía str para no arrastrar el error
    binario del float.
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def _iva_mixto(plano: str, numeros: set[Decimal], valor_total: Decimal) -> Decimal | None:
    """IVA de tarifa MIXTA: importe etiquetado como IVA cuya base está impresa.

    Es el caso "IVA 19.00% 88.486 … TOTAL BRUTO 530.316" con total 618.802: el
    documento gravó solo una parte, así que la tarifa global no es legal y el
    nivel 1 no lo ve. Que `total - iva` esté impreso es lo que convierte la
    coincidencia en prueba — un IVA de un renglón suelto no cumple eso.

    Si dos importes distintos reconcilian, es ambiguo y se devuelve None: que lo
    decida la IA en vez de elegir uno al azar.
    """
    candidatos: set[Decimal] = set()
    for m in _ETIQUETA_IVA.finditer(plano):
        for v in _numeros(plano[m.end():m.end() + _VENTANA_IVA]):
            base = valor_total - v
            if v < _IVA_MINIMO or base <= 0 or v / base > _TARIFA_MAXIMA:
                continue
            if _cerca(numeros, base):
                candidatos.add(v.quantize(_CENTAVOS))
    if not candidatos:
        return None
    if max(candidatos) - min(candidatos) <= _TOLERANCIA:  # el mismo importe redondeado
        return max(candidatos)
    return None


def extraer_iva(texto: str | None, valor_total) -> Decimal | None:
    """IVA de la factura en COP, o None si no se puede determinar con certeza."""
    valor_total = a_decimal(valor_total)
    if not texto or valor_total is None or valor_total <= 0:
        return None

    plano = re.sub(r"\s+", " ", texto)
    numeros = _numeros(plano)

    # 1) tarifa legal reconciliada contra el total
    for tarifa in TARIFAS:
        teorico = (valor_total * tarifa / (1 + tarifa)).quantize(_CENTAVOS)
        if _cerca(numeros, teorico):
            return teorico

    # 2) tarifa mixta: IVA impreso cuya base reconcilia con el total. VA ANTES del
    # nivel 3: estos documentos imprimen su total pegado a "SubTotal"/"TOTAL BRUTO"
    # y la regla de exención los daba por exentos aunque el IVA estuviera escrito
    # al lado (18 facturas y 3 notas crédito reales).
    mixto = _iva_mixto(plano, numeros, valor_total)
    if mixto is not None:
        return mixto

    # 3) el total impreso como base/subtotal => la factura no lleva IVA
    for m in _ETIQUETA_BASE.finditer(plano):
        if _cerca(_numeros(plano[m.end():m.end() + _VENTANA_BASE]), valor_total):
            return Decimal("0.00")

    return None


def resolver_iva(texto: str | None, valor_total,
                 pdf: bytes | None = None,
                 usar_ia: bool = False) -> tuple[Decimal | None, bool]:
    """Cascada completa: aritmética (gratis) y, como ÚLTIMO recurso, IA.

    Devuelve (iva, uso_ia). La IA solo se consulta si `usar_ia` y los dos
    niveles determinísticos no decidieron — el mismo criterio que la asignación
    de área y el vencimiento: primero lo gratis, la IA nunca por defecto.
    """
    valor_total = a_decimal(valor_total)
    iva = extraer_iva(texto, valor_total)
    if iva is not None or not usar_ia:
        return iva, False

    from . import iva_ia  # import local: solo se carga si se usa IA

    iva = iva_ia.sugerir_iva(pdf, texto, valor_total)
    return iva, iva is not None


def subtotal(valor_total, iva: Decimal | None) -> Decimal | None:
    """Valor sin IVA. Con IVA desconocido devuelve el total tal cual: el
    consumidor debe distinguirlo por `iva is None` (la UI lo marca)."""
    valor_total = a_decimal(valor_total)
    if valor_total is None:
        return None
    return valor_total - (iva or Decimal(0))
