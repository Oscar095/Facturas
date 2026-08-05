"""Extracción de la fecha de vencimiento desde el texto del PDF (sin IA, gratis).

El portal Siesa no expone el vencimiento (ni en el JSON del listado, ni como
XML descargable; el catálogo DIAN ahora exige login), así que se lee del texto
que ya extraemos con pypdf (`facturas.texto_pdf`).

Estrategia validada contra los PDF reales de la BD:
  - Se ubica la palabra clave (vencimiento / límite de pago / fecha de pago...).
  - Se recolectan TODAS las fechas en una ventana alrededor de la palabra —
    alrededor y no solo después, porque el texto de PDFs con layout en columnas
    queda revuelto (el valor puede aparecer antes de la etiqueta).
  - Se devuelve la MÁS TARDÍA de las fechas válidas de esa ventana: cerca de la
    etiqueta suelen convivir emisión y vencimiento, y el vencimiento nunca es
    anterior a la emisión (si es de contado, son iguales).
  - Sanidad: se descarta lo que quede antes de la emisión o más allá de
    `_MAX_DIAS`. El límite es deliberadamente ajustado (no "generoso"): toda
    factura imprime el rango de vigencia de la resolución DIAN (típicamente 2
    años), y con una ventana amplia esa fecha se cuela como vencimiento. En los
    datos reales de la BD ningún plazo pasa de 62 días.

Formatos reales cubiertos: 17/7/2026 · 17-07-2026 · 2026-09-19 · 2026-SEP-06 ·
"DÍA MES AÑO ... 24 07 2026" (columnas) · fechas pegadas "22/07/202607/09/2026".
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger("vencimiento")

_CLAVES = re.compile(
    r"venc|l[ií]mite de pago|fecha de pago|pagar hasta|due date"
    r"|pag\w*\s+antes\s+de",  # "Pague/Páguese/Pagar antes de"
    re.IGNORECASE,
)

_MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
          "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12,
          # variantes largas y en inglés que aparecen en algunos proveedores
          "SET": 9, "SEPT": 9, "JAN": 1, "APR": 4, "AUG": 8, "DEC": 12}

# (regex, orden de grupos -> (año, mes, día))
_PATRONES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"), "amd"),           # 2026-09-19
    (re.compile(r"\b(20\d{2})-([A-Z]{3,4})-(\d{1,2})\b", re.I), "amd_txt"),  # 2026-SEP-06
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})"), "dma"),       # 17/7/2026, 17-07-2026
    (re.compile(r"\b(\d{1,2})\s+(\d{1,2})\s+(20\d{2})\b"), "dma"),       # 24 07 2026 (DÍA MES AÑO)
    # mes en letras: "20 Ago 2026", "21/ago./2026", "06-SEPTIEMBRE-2026"
    (re.compile(r"\b(\d{1,2})[\s/.-]+([a-zA-Z]{3,10})\.?[\s/.-]+(20\d{2})\b"), "dma_txt"),
    # mes primero: "Agosto 11-2026", "Ago 11 2026"
    (re.compile(r"\b([a-zA-Z]{3,10})\.?\s+(\d{1,2})[\s.,-]+(20\d{2})\b"), "mda_txt"),
]


def _mes(nombre: str) -> int | None:
    """'AGO', 'Agosto', 'agosto.' -> 8. Devuelve None si no es un mes."""
    return _MESES.get(nombre.upper()[:3])

_ANTES = 45   # chars de ventana antes de la palabra clave (layouts en columnas)
_DESPUES = 75

# Respaldo: muchos proveedores no imprimen la fecha, solo el plazo de crédito
# ("CREDITO 45 DIAS", "Forma de pago: 60 dias") -> vencimiento = emisión + N.
_PLAZO = re.compile(
    r"(?:cr[eé]dito|plazo|condiciones? de pago|forma de pago)"
    r"[^\n]{0,60}?\b(\d{1,3})\s*d[ií]as",
    re.IGNORECASE,
)
# Plazo máximo aceptado (ver docstring): cubre con margen los plazos reales
# (0–62 días observados) sin dejar pasar la vigencia de la resolución DIAN.
_MAX_DIAS = 180


def _fechas_en(fragmento: str) -> list[datetime]:
    # Fechas pegadas por el layout ("22/07/202607/09/2026"): separar el año de la
    # fecha que le sigue para que el \b de los patrones las encuentre a ambas.
    fragmento = re.sub(r"(20\d{2})(?=\d{1,2}[/-])", r"\1 ", fragmento)
    fechas = []
    for patron, orden in _PATRONES:
        for m in patron.finditer(fragmento):
            try:
                if orden == "amd":
                    f = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                elif orden == "amd_txt":
                    mes = _mes(m.group(2))
                    if not mes:
                        continue
                    f = datetime(int(m.group(1)), mes, int(m.group(3)))
                elif orden == "dma_txt":
                    mes = _mes(m.group(2))
                    if not mes:
                        continue
                    f = datetime(int(m.group(3)), mes, int(m.group(1)))
                elif orden == "mda_txt":
                    mes = _mes(m.group(1))
                    if not mes:
                        continue
                    f = datetime(int(m.group(3)), mes, int(m.group(2)))
                else:  # dma
                    f = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                fechas.append(f)
            except ValueError:  # 31/02, mes 13, etc.
                continue
    return fechas


def extraer_vencimiento(texto: str | None,
                        fecha_emision: datetime | None = None) -> datetime | None:
    """Mejor esfuerzo: None si el texto no permite decidir con confianza."""
    if not texto:
        return None

    if fecha_emision is not None:
        minimo = fecha_emision - timedelta(days=1)  # tolera desfase de horas
        maximo = fecha_emision + timedelta(days=_MAX_DIAS)
    else:
        minimo, maximo = datetime(2015, 1, 1), datetime(2100, 1, 1)

    # 1) fecha explícita junto a la etiqueta. Se juntan las candidatas de TODAS
    # las apariciones (una factura suele repetir el dato: una vez como cabecera
    # de columna lejos de su valor y otra pegada a él) y se toma la más tardía:
    # cerca de la etiqueta suelen convivir emisión y vencimiento, y el
    # vencimiento nunca es anterior. El rango de sanidad acota el riesgo.
    candidatas: list[datetime] = []
    for m in _CLAVES.finditer(texto):
        ventana = texto[max(0, m.start() - _ANTES):m.end() + _DESPUES]
        candidatas += [f for f in _fechas_en(ventana) if minimo <= f <= maximo]
    if candidatas:
        return max(candidatas)

    # 2) respaldo por plazo de crédito: solo sirve con fecha de emisión conocida
    if fecha_emision is not None:
        m = _PLAZO.search(texto)
        if m:
            dias = int(m.group(1))
            if 0 <= dias <= _MAX_DIAS:
                return fecha_emision + timedelta(days=dias)

    # 3) último respaldo para PDFs con layout revuelto (la etiqueta queda lejos
    # de su valor): si el documento menciona vencimiento y tiene UNA SOLA fecha
    # posterior a la emisión, esa es. Si hay varias, es ambiguo y no se decide.
    if fecha_emision is not None and _CLAVES.search(texto):
        futuras = {f for f in _fechas_en(texto) if fecha_emision < f <= maximo}
        if len(futuras) == 1:
            return futuras.pop()
    return None


def resolver_vencimiento(texto: str | None, fecha_emision: datetime | None = None,
                         pdf: bytes | None = None,
                         usar_ia: bool = False) -> tuple[datetime | None, bool]:
    """Cascada completa: regex (gratis) y, como ÚLTIMO recurso, IA.

    Devuelve (fecha, uso_ia). La IA solo se consulta si `usar_ia` y los tres
    niveles determinísticos no decidieron — el mismo criterio que la asignación
    de área: primero lo gratis, la IA nunca por defecto.
    """
    venc = extraer_vencimiento(texto, fecha_emision)
    if venc is not None or not usar_ia:
        return venc, False

    from . import vencimiento_ia  # import local: solo se carga si se usa IA

    venc = vencimiento_ia.sugerir_vencimiento(pdf, texto, fecha_emision)
    if venc is not None:
        log.info("Vencimiento resuelto por IA: %s", venc.date())
    return venc, venc is not None
