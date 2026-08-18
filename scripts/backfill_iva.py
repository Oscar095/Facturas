"""Backfill de facturas.iva desde texto_pdf (idempotente, gratis, sin IA).

Solo toca facturas con iva NULL; nunca sobreescribe un IVA existente (p. ej. el
que extrajo la IA en la carga manual). Lo que el extractor no pueda determinar
con certeza se deja en NULL — la UI marca esas facturas como "IVA no
discriminado" en vez de mostrar un subtotal inventado.

Uso:
  .venv/Scripts/python.exe scripts/backfill_iva.py            # simulación
  .venv/Scripts/python.exe scripts/backfill_iva.py --aplicar  # escribe
"""
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "backend")

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura  # noqa: E402
from app.services.iva import extraer_iva  # noqa: E402

aplicar = "--aplicar" in sys.argv

db = SessionLocal()
filas = db.execute(select(Factura).where(Factura.iva.is_(None))).scalars().all()

stats = Counter()
muestras = []
suma_total = suma_subtotal = Decimal(0)
for f in filas:
    if not f.texto_pdf:
        stats["sin_texto"] += 1
        continue
    iva = extraer_iva(f.texto_pdf, f.valor_total)
    if iva is None:
        stats["sin_hallazgo"] += 1
        continue
    stats["exenta" if iva == 0 else "con_iva"] += 1
    if f.valor_total is not None:
        suma_total += f.valor_total
        suma_subtotal += f.valor_total - iva
    if iva > 0 and len(muestras) < 12:
        pct = 100 * iva / (f.valor_total - iva)
        muestras.append(f"  {f.numero:<14} total={f.valor_total:>14,.2f} "
                        f"iva={iva:>12,.2f} base={f.valor_total - iva:>14,.2f} ({pct:.0f}%)")
    if aplicar:
        f.iva = iva

if aplicar:
    db.commit()
db.close()

total = len(filas)
resueltas = stats["con_iva"] + stats["exenta"]
print(f"Facturas con iva NULL: {total}")
print(f"  con IVA discriminado: {stats['con_iva']}")
print(f"  exentas (iva = 0):    {stats['exenta']}")
print(f"  TOTAL resuelto:       {resueltas} ({100 * resueltas / max(total, 1):.0f}%)")
print(f"  sin hallazgo:         {stats['sin_hallazgo']}")
print(f"  sin texto_pdf:        {stats['sin_texto']}")
if suma_total:
    print(f"\nEn las resueltas: total {suma_total:,.0f} -> subtotal {suma_subtotal:,.0f} "
          f"(IVA descontado: {suma_total - suma_subtotal:,.0f})")
print("\nMuestras:")
print("\n".join(muestras))
print(f"\n{'APLICADO (BD actualizada).' if aplicar else 'SIMULACIÓN — nada escrito. Corre con --aplicar para guardar.'}")
