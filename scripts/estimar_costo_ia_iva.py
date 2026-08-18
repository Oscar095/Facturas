"""Estima el costo mensual de usar IA para el IVA.

Mide tokens REALES con /v1/messages/count_tokens (gratis, no genera respuesta)
sobre una muestra de las facturas que hoy quedan sin IVA, y extrapola al ritmo
mensual observado en la BD.

Uso: .venv/Scripts/python.exe scripts/estimar_costo_ia_iva.py [muestra]
"""
import base64
import sys

sys.path.insert(0, "backend")

import anthropic  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services import iva_ia  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402

MUESTRA = int(sys.argv[1]) if len(sys.argv) > 1 else 8
PRECIO_ENTRADA = 1.0 / 1_000_000   # Haiku 4.5: US$1 por millón de tokens de entrada
PRECIO_SALIDA = 5.0 / 1_000_000    # US$5 por millón de tokens de salida
TOKENS_SALIDA = 30                 # max_tokens=80; dos cifras + cita ~30

cliente = anthropic.Anthropic(api_key=settings.anthropic_api_key)
almacen = get_almacen()
db = SessionLocal()


def contar(pdf, texto, total):
    """Arma el MISMO mensaje que enviaría iva_ia y cuenta sus tokens."""
    texto = (texto or "").strip()
    instruccion = f"{iva_ia._INSTRUCCION}\nEl total de esta factura es {total}."
    if len(texto) >= iva_ia._MIN_TEXTO_UTIL:
        contenido = [{"type": "text",
                      "text": f'{instruccion}\n\nTexto de la factura:\n'
                              f'"""{iva_ia._recorte(texto)}"""'}]
    else:
        contenido = [
            {"type": "document", "source": {"type": "base64",
             "media_type": "application/pdf",
             "data": base64.b64encode(iva_ia._paginas_utiles(pdf)).decode()}},
            {"type": "text", "text": instruccion},
        ]
    r = cliente.messages.count_tokens(
        model=iva_ia.MODELO,
        system="Extraes dos cifras de facturas. Respondes SOLO 'base|iva|cita' o NULL.",
        messages=[{"role": "user", "content": contenido}],
    )
    return r.input_tokens


pendientes = db.execute(select(Factura).where(Factura.iva.is_(None))).scalars().all()
con_texto = [f for f in pendientes if f.texto_pdf]
escaneadas = [f for f in pendientes if not f.texto_pdf and f.blob_pdf]

print(f"Facturas que hoy quedan sin IVA: {len(pendientes)}")
print(f"  con texto (IA solo-texto, barata): {len(con_texto)}")
print(f"  escaneadas (IA con visión, cara):  {len(escaneadas)}\n")

prom = {}
for etiqueta, grupo, necesita_pdf in (("texto", con_texto, False),
                                      ("vision", escaneadas, True)):
    if not grupo:
        prom[etiqueta] = 0
        continue
    tokens = []
    for f in grupo[:MUESTRA]:
        pdf = almacen.descargar(f.blob_pdf) if necesita_pdf else None
        try:
            tokens.append(contar(pdf, f.texto_pdf, f.valor_total))
        except Exception as e:  # noqa: BLE001
            print(f"  aviso ({f.numero}): {e}")
    prom[etiqueta] = sum(tokens) // len(tokens) if tokens else 0
    print(f"{etiqueta}: {len(tokens)} medidas, tokens de entrada "
          f"min={min(tokens)} prom={prom[etiqueta]} max={max(tokens)}")

total = db.scalar(select(func.count()).select_from(Factura))
minf = db.scalar(select(func.min(Factura.fecha_recepcion)))
maxf = db.scalar(select(func.max(Factura.fecha_recepcion)))
db.close()
dias = max((maxf - minf).days, 1)
por_mes = total * 30 / dias

p_texto = len(con_texto) / total
p_vision = len(escaneadas) / total
n_texto, n_vision = por_mes * p_texto, por_mes * p_vision
costo_texto = n_texto * (prom["texto"] * PRECIO_ENTRADA + TOKENS_SALIDA * PRECIO_SALIDA)
costo_vision = n_vision * (prom["vision"] * PRECIO_ENTRADA + TOKENS_SALIDA * PRECIO_SALIDA)

print(f"\nRitmo observado: {total} facturas en {dias} días -> ~{por_mes:.0f} facturas/mes")
print(f"De esas irían a la IA: ~{n_texto:.0f} por texto + ~{n_vision:.0f} por visión "
      f"= ~{n_texto + n_vision:.0f}/mes ({100 * (p_texto + p_vision):.0f}% del total)")
print("\nCOSTO MENSUAL ESTIMADO (Haiku 4.5, US$1/MTok entrada + US$5/MTok salida):")
print(f"  solo texto: US$ {costo_texto:.3f}")
print(f"  visión:     US$ {costo_vision:.3f}")
print(f"  TOTAL:      US$ {costo_texto + costo_vision:.2f} / mes")
print(f"\nMás el backfill histórico (una sola vez, {len(pendientes)} facturas): US$ "
      f"{(len(con_texto) * prom['texto'] + len(escaneadas) * prom['vision']) * PRECIO_ENTRADA + len(pendientes) * TOKENS_SALIDA * PRECIO_SALIDA:.2f}")
