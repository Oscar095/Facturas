"""Backfill de notas_credito.iva (idempotente).

El panel netea las notas crédito contra lo facturado y todo se mide SIN IVA
(ver routers/panel.py): una nota con el IVA incluido restaría de más. Este
script deduce el IVA de las notas históricas con la misma cascada de las
facturas (services/iva.py) y solo toca filas con iva NULL.

A diferencia del backfill de facturas, aquí SÍ se baja el PDF del Blob aunque no
se use IA: la mayoría de las notas históricas se guardaron sin `texto_pdf` (no
existía la extracción cuando se ingirieron) y sacarlo con pypdf es gratis. Ese
texto se guarda también, que es lo que necesitan los patrones de área.

Uso:
  .venv/Scripts/python.exe scripts/backfill_iva_notas_credito.py            # simulación
  .venv/Scripts/python.exe scripts/backfill_iva_notas_credito.py --aplicar  # escribe (sin IA)
  .venv/Scripts/python.exe scripts/backfill_iva_notas_credito.py --ia       # simula con IA
  .venv/Scripts/python.exe scripts/backfill_iva_notas_credito.py --ia --aplicar
"""
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, "backend")

from sqlalchemy import select, update  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import NotaCredito  # noqa: E402
from app.services.blob_storage import get_almacen  # noqa: E402
from app.services.iva import resolver_iva  # noqa: E402
from app.services.pdf_texto import extraer_texto  # noqa: E402

aplicar = "--aplicar" in sys.argv
usar_ia = "--ia" in sys.argv
almacen = get_almacen()

db = SessionLocal()
filas = db.execute(select(NotaCredito).where(NotaCredito.iva.is_(None))).scalars().all()

stats = Counter()
muestras = []
cambios: list[tuple[int, Decimal, str | None]] = []
suma_total = suma_subtotal = Decimal(0)

for n in filas:
    texto, texto_nuevo, pdf = n.texto_pdf, None, None
    if not texto and n.blob_pdf:
        # gratis: pypdf sobre el PDF que ya está en el Blob
        try:
            pdf = almacen.descargar(n.blob_pdf)
            texto = texto_nuevo = extraer_texto(pdf)
        except Exception as e:  # noqa: BLE001
            print(f"  aviso: no se pudo bajar {n.blob_pdf}: {e}")
    if not texto:
        stats["sin_texto"] += 1
        if not usar_ia:
            continue
        # escaneada: la IA la lee por visión, así que hace falta el PDF
        if pdf is None and n.blob_pdf:
            try:
                pdf = almacen.descargar(n.blob_pdf)
            except Exception as e:  # noqa: BLE001
                print(f"  aviso: no se pudo bajar {n.blob_pdf}: {e}")

    iva, por_ia = resolver_iva(texto, n.valor_total, pdf=pdf, usar_ia=usar_ia)
    if iva is None:
        stats["sin_hallazgo" if texto else "sin_resolver_escaneada"] += 1
        # aunque no se resuelva el IVA, el texto extraído vale la pena guardarlo
        if texto_nuevo:
            cambios.append((n.id, None, texto_nuevo))
        continue
    if por_ia:
        stats["por_ia"] += 1
    stats["exenta" if iva == 0 else "con_iva"] += 1
    if n.valor_total is not None:
        suma_total += n.valor_total
        suma_subtotal += n.valor_total - iva
    if len(muestras) < 15:
        pct = 100 * iva / (n.valor_total - iva) if iva and n.valor_total else 0
        muestras.append(f"  {n.numero:<14} total={n.valor_total:>14,.2f} "
                        f"iva={iva:>12,.2f} base={n.valor_total - iva:>14,.2f} ({pct:.0f}%)"
                        + ("  [IA]" if por_ia else ""))
    cambios.append((n.id, iva, texto_nuevo))

db.close()

if aplicar and cambios:
    # sesión nueva al final: la corrida con IA dura minutos y la conexión a Azure
    # SQL puede caerse en el camino (ya pasó en el backfill de facturas)
    db2 = SessionLocal()
    for i in range(0, len(cambios), 50):
        for nid, valor, texto_nuevo in cambios[i:i + 50]:
            datos = {}
            if valor is not None:
                datos["iva"] = valor
            if texto_nuevo:
                datos["texto_pdf"] = texto_nuevo
            if datos:
                db2.execute(update(NotaCredito).where(NotaCredito.id == nid).values(**datos))
        db2.commit()
    db2.close()

total = len(filas)
resueltas = stats["con_iva"] + stats["exenta"]
print(f"Notas crédito con iva NULL: {total}")
print(f"  con IVA discriminado: {stats['con_iva']}")
print(f"  exentas (iva = 0):    {stats['exenta']}")
print(f"  de esas, por IA:      {stats['por_ia']}")
print(f"  TOTAL resuelto:       {resueltas} ({100 * resueltas / max(total, 1):.0f}%)")
print(f"  sin hallazgo:         {stats['sin_hallazgo']}")
print(f"  sin texto extraíble:  {stats['sin_texto']} "
      f"(sin resolver: {stats['sin_resolver_escaneada']})")
if suma_total:
    print(f"\nEn las resueltas: total {suma_total:,.0f} -> subtotal {suma_subtotal:,.0f} "
          f"(IVA que ya no se le resta al área: {suma_total - suma_subtotal:,.0f})")
print("\nMuestras:")
print("\n".join(muestras))
print(f"\n{'APLICADO (BD actualizada).' if aplicar else 'SIMULACIÓN — nada escrito. Corre con --aplicar para guardar.'}")
