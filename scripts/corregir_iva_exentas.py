"""Corrige las facturas marcadas como EXENTAS que en realidad traen IVA impreso.

El nivel de exención de `services/iva.py` daba por exenta toda factura cuyo total
apareciera cerca de una etiqueta "SubTotal"/"TOTAL BRUTO". En las facturas de
**tarifa mixta** (parte gravada, parte exenta: servicios temporales con base
gravable especial/AIU, o una factura con un ítem al 19% y otro al 0%) el total se
imprime justo ahí, al lado del IVA — así que quedaban con `iva = 0` aunque el
importe estuviera escrito. El nivel nuevo (`_iva_mixto`) las resuelve.

Este script re-evalúa SOLO las facturas con `iva = 0` y les escribe el IVA cuando
la vía gratis ahora encuentra uno respaldado por la aritmética (el importe está
impreso Y `total - iva` también). No usa IA y no toca ninguna otra fila.

Es idempotente: al correrlo de nuevo esas facturas ya no tienen iva = 0.

Uso:
  .venv/Scripts/python.exe scripts/corregir_iva_exentas.py             # simulación
  .venv/Scripts/python.exe scripts/corregir_iva_exentas.py --aplicar
"""
import sys
from decimal import Decimal

sys.path.insert(0, "backend")

from sqlalchemy import select, update  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Factura, NotaCredito  # noqa: E402
from app.services.iva import extraer_iva  # noqa: E402

aplicar = "--aplicar" in sys.argv

db = SessionLocal()
cambios: list[tuple[type, int, Decimal]] = []
suma = Decimal(0)

for modelo, etiqueta in ((Factura, "Factura"), (NotaCredito, "Nota crédito")):
    filas = db.execute(
        select(modelo).where(modelo.iva == 0, modelo.texto_pdf.isnot(None))
    ).scalars().all()
    encontrados = 0
    for f in filas:
        iva = extraer_iva(f.texto_pdf, f.valor_total)
        if iva is None or iva <= 0:
            continue
        encontrados += 1
        suma += iva
        cambios.append((modelo, f.id, iva))
        print(f"  {etiqueta:<12} {f.numero:<14} total={f.valor_total:>14,.0f}  "
              f"IVA 0 -> {iva:>12,.2f}  ({100 * iva / (f.valor_total - iva):.1f}%)")
    print(f"— {etiqueta}: {encontrados} de {len(filas)} marcadas exentas traían IVA impreso")

db.close()

if aplicar and cambios:
    db2 = SessionLocal()
    for modelo, fid, iva in cambios:
        db2.execute(update(modelo).where(modelo.id == fid).values(iva=iva))
    db2.commit()
    db2.close()

print(f"\nTotal a reclasificar de base a IVA: {suma:,.0f}")
print(f"{'APLICADO (BD actualizada).' if aplicar else 'SIMULACIÓN — nada escrito. Corre con --aplicar para guardar.'}")
